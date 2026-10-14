import io
import csv
from datetime import date, timedelta
import datetime
from decimal import Decimal

import pytest
import openpyxl
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth.models import User

from accounts.models import UserProfile, RoleChoices
from members.models import Member, MemberStatus, DepartmentChoices
from plans.models import Plan, MemberPlanAssignment
from payments.models import Payment, PaymentMode, PaymentStatus, PaymentAdjustment, AdjustmentType
from payments.services import record_payment
from reports.services import (
    get_daily_collection_data,
    get_revenue_summary_data,
    get_defaulters_data,
    get_member_demographics_data,
    export_to_excel,
    export_to_csv,
    export_to_pdf,
)


@pytest.fixture
def superadmin_user(db):
    user = User.objects.create_user(username='rep_admin', password='AdminPassword@2026!')
    UserProfile.objects.create(user=user, role=RoleChoices.SUPER_ADMIN, phone='+919876543200')
    return user


@pytest.fixture
def accountant_user(db):
    user = User.objects.create_user(username='rep_acct', password='AcctPassword@2026!')
    UserProfile.objects.create(user=user, role=RoleChoices.ACCOUNTANT, phone='+919876543201')
    return user


@pytest.fixture
def viewer_user(db):
    user = User.objects.create_user(username='rep_view', password='ViewPassword@2026!')
    UserProfile.objects.create(user=user, role=RoleChoices.VIEWER, phone='+919876543202')
    return user


@pytest.fixture
def sample_report_data(db):
    """Sets up members, plans, assignments, and payments across various dates and modes."""
    plan1 = Plan.objects.create(
        name="Annual Regular",
        duration_months=12,
        fee=Decimal('2400.00'),
        grace_period_days=15
    )
    plan2 = Plan.objects.create(
        name="Quarterly Regular",
        duration_months=3,
        fee=Decimal('600.00'),
        grace_period_days=10
    )

    # Member 1: Active, Mechanical, paid
    m1 = Member.objects.create(
        name="Sunil Verma",
        phone="+919876500001",
        employee_id="PF-1001",
        department=DepartmentChoices.MECHANICAL,
        status=MemberStatus.ACTIVE,
        whatsapp_opt_in=True
    )
    a1 = MemberPlanAssignment.objects.create(
        member=m1,
        plan=plan1,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        base_fee=Decimal('2400.00'),
        final_fee=Decimal('2400.00'),
        is_current=True
    )
    # Payment on 2026-06-15 via UPI
    p1 = Payment.objects.create(
        member=m1,
        plan_assignment=a1,
        amount=Decimal('2400.00'),
        payment_date=date(2026, 6, 15),
        payment_mode=PaymentMode.UPI,
        status=PaymentStatus.COMPLETED
    )

    # Member 2: Due, Electrical, partial payment
    m2 = Member.objects.create(
        name="Anita Rao",
        phone="+919876500002",
        employee_id="PF-1002",
        department=DepartmentChoices.ELECTRICAL,
        status=MemberStatus.DUE,
        whatsapp_opt_in=False
    )
    a2 = MemberPlanAssignment.objects.create(
        member=m2,
        plan=plan1,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        base_fee=Decimal('2400.00'),
        final_fee=Decimal('2400.00'),
        is_current=True
    )
    # Payment on 2026-06-15 via Cash
    p2 = Payment.objects.create(
        member=m2,
        plan_assignment=a2,
        amount=Decimal('1000.00'),
        payment_date=date(2026, 6, 15),
        payment_mode=PaymentMode.CASH,
        status=PaymentStatus.COMPLETED
    )

    # Member 3: Expired, Operating, no payments
    m3 = Member.objects.create(
        name="Ramesh Yadav",
        phone="+919876500003",
        employee_id="PF-1003",
        department=DepartmentChoices.OPERATING,
        status=MemberStatus.EXPIRED,
        whatsapp_opt_in=True
    )
    a3 = MemberPlanAssignment.objects.create(
        member=m3,
        plan=plan2,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 3, 31),
        base_fee=Decimal('600.00'),
        final_fee=Decimal('600.00'),
        is_current=True
    )

    return {
        'members': [m1, m2, m3],
        'plans': [plan1, plan2],
        'payments': [p1, p2],
    }


@pytest.mark.django_db
class TestReportCalculations:
    """Tests the mathematical and aggregation accuracy of report service functions."""

    def test_daily_collection_calculation(self, sample_report_data):
        target_date = date(2026, 6, 15)
        data = get_daily_collection_data(target_date)

        assert data['total_count'] == 2
        assert data['total_amount'] == Decimal('3400.00')
        assert data['mode_breakdown'][PaymentMode.UPI]['count'] == 1
        assert data['mode_breakdown'][PaymentMode.UPI]['amount'] == Decimal('2400.00')
        assert data['mode_breakdown'][PaymentMode.CASH]['count'] == 1
        assert data['mode_breakdown'][PaymentMode.CASH]['amount'] == Decimal('1000.00')

        # Add an adjustment of 200 on that date and check net collection
        p1 = sample_report_data['payments'][0]
        adj = PaymentAdjustment.objects.create(
            payment=p1,
            adjustment_type=AdjustmentType.REFUND,
            amount=Decimal('200.00'),
            reason="Partial waiver refund"
        )
        PaymentAdjustment.objects.filter(id=adj.id).update(
            created_at=timezone.make_aware(datetime.datetime(2026, 6, 15, 12, 0))
        )
        data_adjusted = get_daily_collection_data(target_date)
        assert data_adjusted['adjustments'] == Decimal('200.00')
        assert data_adjusted['net_collection'] == Decimal('3200.00')


    def test_revenue_summary_calculation(self, sample_report_data):
        data = get_revenue_summary_data(start_date=date(2026, 6, 1), end_date=date(2026, 6, 30))

        assert data['total_transactions'] == 2
        assert data['total_revenue'] == Decimal('3400.00')
        assert "Annual Regular" in data['plan_summary']
        assert data['plan_summary']['Annual Regular']['count'] == 2
        assert data['plan_summary']['Annual Regular']['amount'] == Decimal('3400.00')

    def test_defaulters_data_calculation(self, sample_report_data):
        data = get_defaulters_data()

        # Member 2 (Anita Rao, 1400 due) and Member 3 (Ramesh Yadav, 600 due)
        assert data['total_count'] == 2
        assert data['total_outstanding'] == Decimal('2000.00')

        # Filter by department
        data_elec = get_defaulters_data(department=DepartmentChoices.ELECTRICAL)
        assert data_elec['total_count'] == 1
        assert data_elec['defaulters'][0]['name'] == "Anita Rao"
        assert data_elec['defaulters'][0]['balance_due'] == Decimal('1400.00')

    def test_member_demographics_data_calculation(self, sample_report_data):
        data = get_member_demographics_data()

        assert data['total_members'] == 3
        assert data['dept_counts']['Mechanical Engineering'] == 1
        assert data['dept_counts']['Electrical Engineering'] == 1
        assert data['dept_counts']['Operating / Traffic'] == 1
        assert data['status_counts']['Active'] == 1
        assert data['status_counts']['Due'] == 1
        assert data['status_counts']['Expired'] == 1
        assert data['with_plan_count'] == 3
        assert data['opt_in_count'] == 2
        assert data['opt_out_count'] == 1


class TestExportGenerators:
    """Tests that Excel, CSV, and PDF exports generate valid non-empty payloads."""

    def test_export_to_excel_valid_workbook(self):
        headers = ["Receipt No", "Member Name", "Amount (₹)"]
        rows = [
            ["RCP-001", "Sunil Verma", 2400.00],
            ["RCP-002", "Anita Rao", 1000.00],
        ]
        summary = {"Total Collected": "₹3,400.00"}

        excel_bytes = export_to_excel("Test Daily Collection", headers, rows, summary)
        assert isinstance(excel_bytes, bytes)
        assert len(excel_bytes) > 0

        # Verify it can be loaded back via openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(excel_bytes))
        ws = wb.active
        assert ws.title == "Report"
        assert "RAILWAY EMPLOYEES' INSTITUTE" in ws.cell(row=1, column=1).value

    def test_export_to_csv_valid_content(self):
        headers = ["Receipt No", "Member Name", "Amount"]
        rows = [
            ["RCP-001", "Sunil Verma", 2400.00],
            ["RCP-002", "Anita Rao", 1000.00],
        ]

        csv_str = export_to_csv(headers, rows)
        reader = list(csv.reader(io.StringIO(csv_str)))
        assert reader[0] == headers
        assert reader[1] == ["RCP-001", "Sunil Verma", "2400.0"]
        assert reader[2] == ["RCP-002", "Anita Rao", "1000.0"]

    def test_export_to_pdf_valid_document(self):
        headers = ["Receipt No", "Member Name", "Amount"]
        rows = [
            ["RCP-001", "Sunil Verma", "2400.00"],
            ["RCP-002", "Anita Rao", "1000.00"],
        ]
        summary = {"Total": "₹3,400.00"}

        pdf_bytes = export_to_pdf("Test Report", headers, rows, summary, orientation='landscape')
        assert isinstance(pdf_bytes, bytes)
        assert pdf_bytes.startswith(b'%PDF-')
        assert len(pdf_bytes) > 500


@pytest.mark.django_db
class TestReportViewsAndPermissions:
    """Tests web endpoints for report viewing and export downloads across user roles."""

    def _login_as(self, client, user):
        client.force_login(user)
        session = client.session
        session['otp_verified'] = True
        session.save()

    def test_unauthenticated_user_redirected(self, client):
        urls = [
            reverse('reports:hub'),
            reverse('reports:daily_collection'),
            reverse('reports:revenue_summary'),
            reverse('reports:defaulters'),
            reverse('reports:demographics'),
        ]
        for url in urls:
            resp = client.get(url)
            assert resp.status_code == 302
            assert reverse('accounts:login') in resp.url

    def test_reports_hub_view_access(self, client, viewer_user, sample_report_data):
        self._login_as(client, viewer_user)
        resp = client.get(reverse('reports:hub'))
        assert resp.status_code == 200
        assert "Financial &amp; Member Reports" in resp.content.decode()

    def test_daily_collection_view_and_exports(self, client, accountant_user, sample_report_data):
        self._login_as(client, accountant_user)
        url = reverse('reports:daily_collection')

        # 1. HTML View
        resp = client.get(f"{url}?date=2026-06-15")
        assert resp.status_code == 200
        assert "Sunil Verma" in resp.content.decode()

        # 2. Excel Export
        resp_excel = client.get(f"{url}?date=2026-06-15&export=excel")
        assert resp_excel.status_code == 200
        assert resp_excel['Content-Type'] == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        assert 'daily_collection_20260615.xlsx' in resp_excel['Content-Disposition']

        # 3. CSV Export
        resp_csv = client.get(f"{url}?date=2026-06-15&export=csv")
        assert resp_csv.status_code == 200
        assert resp_csv['Content-Type'] == 'text/csv; charset=utf-8'
        assert 'daily_collection_20260615.csv' in resp_csv['Content-Disposition']

        # 4. PDF Export
        resp_pdf = client.get(f"{url}?date=2026-06-15&export=pdf")
        assert resp_pdf.status_code == 200
        assert resp_pdf['Content-Type'] == 'application/pdf'
        assert 'daily_collection_20260615.pdf' in resp_pdf['Content-Disposition']

    def test_revenue_summary_view_and_exports(self, client, superadmin_user, sample_report_data):
        self._login_as(client, superadmin_user)
        url = reverse('reports:revenue_summary')

        # 1. HTML View
        resp = client.get(f"{url}?start_date=2026-06-01&end_date=2026-06-30")
        assert resp.status_code == 200
        assert "Revenue Summary Report" in resp.content.decode()

        # 2. Excel Export
        resp_excel = client.get(f"{url}?start_date=2026-06-01&end_date=2026-06-30&export=excel")
        assert resp_excel.status_code == 200
        assert 'revenue_report_20260601_20260630.xlsx' in resp_excel['Content-Disposition']

        # 3. PDF Export
        resp_pdf = client.get(f"{url}?start_date=2026-06-01&end_date=2026-06-30&export=pdf")
        assert resp_pdf.status_code == 200
        assert 'revenue_report_20260601_20260630.pdf' in resp_pdf['Content-Disposition']

    def test_defaulters_view_and_exports(self, client, accountant_user, sample_report_data):
        self._login_as(client, accountant_user)
        url = reverse('reports:defaulters')

        # 1. HTML View
        resp = client.get(url)
        assert resp.status_code == 200
        assert "Anita Rao" in resp.content.decode()

        # 2. Filter by department
        resp_filtered = client.get(f"{url}?department={DepartmentChoices.ELECTRICAL}")
        assert resp_filtered.status_code == 200
        assert "Anita Rao" in resp_filtered.content.decode()
        assert "Ramesh Yadav" not in resp_filtered.content.decode()

        # 3. Excel Export
        resp_excel = client.get(f"{url}?export=excel")
        assert resp_excel.status_code == 200
        assert 'defaulters_report_' in resp_excel['Content-Disposition']

        # 4. PDF Export
        resp_pdf = client.get(f"{url}?export=pdf")
        assert resp_pdf.status_code == 200
        assert 'defaulters_report_' in resp_pdf['Content-Disposition']

    def test_demographics_view_and_exports(self, client, viewer_user, sample_report_data):
        self._login_as(client, viewer_user)
        url = reverse('reports:demographics')

        # 1. HTML View
        resp = client.get(url)
        assert resp.status_code == 200
        assert "Member Demographics" in resp.content.decode()

        # 2. Excel Export
        resp_excel = client.get(f"{url}?export=excel")
        assert resp_excel.status_code == 200
        assert 'member_demographics_' in resp_excel['Content-Disposition']

        # 3. CSV Export
        resp_csv = client.get(f"{url}?export=csv")
        assert resp_csv.status_code == 200
        assert 'member_demographics_' in resp_csv['Content-Disposition']
