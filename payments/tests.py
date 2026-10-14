from decimal import Decimal
from datetime import date, timedelta
import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse
from django.core.exceptions import ValidationError

from accounts.models import UserProfile, RoleChoices
from members.models import Member, MemberStatus, DepartmentChoices
from plans.models import Plan, MemberPlanAssignment, LateFeeType
from payments.models import Payment, PaymentAdjustment, PaymentMode, PaymentStatus, AdjustmentType
from payments.services import (
    calculate_member_dues,
    record_payment,
    cancel_payment,
    generate_receipt_pdf,
    sync_member_status_after_payment,
)
from core.utils import number_to_words_inr

@pytest.fixture
def superadmin_user(db):
    user = User.objects.create_user(
        username='superadmin_m4',
        password='TestPassword123!',
        is_staff=True,
        is_superuser=True,
    )
    UserProfile.objects.create(
        user=user,
        role=RoleChoices.SUPER_ADMIN,
        phone='+919876543210',
    )
    return user


@pytest.fixture
def accountant_user(db):
    user = User.objects.create_user(
        username='accountant_m4',
        password='TestPassword123!',
        is_staff=True,
    )
    UserProfile.objects.create(
        user=user,
        role=RoleChoices.ACCOUNTANT,
        phone='+919876543211',
    )
    return user


@pytest.fixture
def event_manager_user(db):
    user = User.objects.create_user(
        username='eventmgr_m4',
        password='TestPassword123!',
        is_staff=True,
    )
    UserProfile.objects.create(
        user=user,
        role=RoleChoices.EVENT_MANAGER,
        phone='+919876543212',
    )
    return user


@pytest.fixture
def viewer_user(db):
    user = User.objects.create_user(
        username='viewer_m4',
        password='TestPassword123!',
        is_staff=True,
    )
    UserProfile.objects.create(
        user=user,
        role=RoleChoices.VIEWER,
        phone='+919876543213',
    )
    return user


@pytest.fixture
def member_with_plan(db):
    m = Member.objects.create(
        name='Suresh Prabhu',
        phone='9876566001',
        department=DepartmentChoices.OPERATING,
        status=MemberStatus.DUE,
    )
    plan = Plan.objects.create(
        name='Annual Membership 2026',
        fee=Decimal('2400.00'),
        duration_months=12,
        is_active=True,
    )
    assignment = MemberPlanAssignment.objects.create(
        member=m,
        plan=plan,
        start_date=date(2026, 1, 1),
        is_current=True,
    )
    return m, assignment


@pytest.mark.django_db
class TestPaymentMathAndDueCalculations:
    """Tests partial payments, running balance, overpayment handling, and status transitions."""

    def test_partial_payment_leaves_correct_balance_and_maintains_due_status(self, member_with_plan, accountant_user):
        member, assignment = member_with_plan
        assert member.status == MemberStatus.DUE

        # Total fee is ₹2400. Pay partial installment of ₹1000
        p1 = record_payment(
            member=member,
            amount=Decimal('1000.00'),
            payment_mode=PaymentMode.UPI,
            reference_number='UPI-PARTIAL-1',
            collected_by=accountant_user,
        )
        assert p1.receipt_number.startswith('RCP-')

        dues = calculate_member_dues(member)
        assert dues['total_due'] == Decimal('2400.00')
        assert dues['total_paid'] == Decimal('1000.00')
        assert dues['balance_due'] == Decimal('1400.00')
        assert dues['excess_paid'] == Decimal('0.00')
        assert dues['is_fully_paid'] is False

        # Member status remains DUE because ₹1400 is still outstanding
        member.refresh_from_db()
        assert member.status == MemberStatus.DUE

    def test_full_payment_transitions_member_status_to_active(self, member_with_plan, accountant_user):
        member, assignment = member_with_plan
        assert member.status == MemberStatus.DUE

        # Pay remaining full balance of ₹2400
        p = record_payment(
            member=member,
            amount=Decimal('2400.00'),
            payment_mode=PaymentMode.BANK_TRANSFER,
            reference_number='NEFT-FULL-PAY',
            collected_by=accountant_user,
        )

        dues = calculate_member_dues(member)
        assert dues['balance_due'] == Decimal('0.00')
        assert dues['is_fully_paid'] is True

        # Member status automatically transitioned to ACTIVE!
        member.refresh_from_db()
        assert member.status == MemberStatus.ACTIVE

    def test_overpayment_handled_gracefully(self, member_with_plan, accountant_user):
        member, assignment = member_with_plan

        # Member pays ₹2500 (overpaying ₹100)
        p = record_payment(
            member=member,
            amount=Decimal('2500.00'),
            payment_mode=PaymentMode.CASH,
            collected_by=accountant_user,
        )

        dues = calculate_member_dues(member)
        assert dues['total_due'] == Decimal('2400.00')
        assert dues['total_paid'] == Decimal('2500.00')
        assert dues['balance_due'] == Decimal('0.00')
        assert dues['excess_paid'] == Decimal('100.00')
        assert dues['is_fully_paid'] is True

        member.refresh_from_db()
        assert member.status == MemberStatus.ACTIVE


@pytest.mark.django_db
class TestPaymentCancellationAndAuditing:
    """Tests cancellation with mandatory reason, due restoration, and adjustment recording."""

    def test_cancelled_payment_restores_due_amount_and_status(self, member_with_plan, accountant_user):
        member, assignment = member_with_plan

        # Pay full ₹2400 -> transitions to ACTIVE
        p = record_payment(
            member=member,
            amount=Decimal('2400.00'),
            payment_mode=PaymentMode.CHEQUE,
            reference_number='CHQ-9901',
            collected_by=accountant_user,
        )
        member.refresh_from_db()
        assert member.status == MemberStatus.ACTIVE

        # Cheque bounces! Accountant cancels payment with mandatory reason
        cancel_payment(p, user=accountant_user, reason='Cheque bounced due to signature mismatch at SBI.')
        
        p.refresh_from_db()
        assert p.is_cancelled is True
        assert p.status == PaymentStatus.CANCELLED
        assert 'Cheque bounced' in p.cancellation_reason
        assert p.cancelled_by == accountant_user

        # Dues are restored to ₹2400
        dues = calculate_member_dues(member)
        assert dues['balance_due'] == Decimal('2400.00')
        assert dues['is_fully_paid'] is False

        # Member status reverted back to DUE
        member.refresh_from_db()
        assert member.status == MemberStatus.DUE

    def test_financial_adjustment_record(self, member_with_plan, accountant_user):
        member, assignment = member_with_plan
        p = record_payment(
            member=member,
            amount=Decimal('2400.00'),
            payment_mode=PaymentMode.UPI,
            collected_by=accountant_user,
        )

        # Record a partial refund adjustment
        adj = PaymentAdjustment.objects.create(
            payment=p,
            adjustment_type=AdjustmentType.REFUND,
            amount=Decimal('400.00'),
            reason='Refund granted due to double debit on member GPay app.',
            adjusted_by=accountant_user,
        )
        assert adj.id is not None
        assert p.adjustments.count() == 1


@pytest.mark.django_db
class TestSequentialReceiptNumbers:
    """Verifies sequential unique receipt number generation under atomic transactions."""

    def test_sequential_unique_receipt_numbers(self):
        r1 = Payment.generate_next_receipt_number(2026)
        r2 = Payment.generate_next_receipt_number(2026)
        r3 = Payment.generate_next_receipt_number(2026)
        
        # When uncommitted in separate calls without existing DB rows, returns 00001
        # When creating real records:
        m = Member.objects.create(name='Test Sequential', phone='9876555111')
        p1 = Payment.objects.create(member=m, amount=100, payment_mode=PaymentMode.CASH)
        p2 = Payment.objects.create(member=m, amount=200, payment_mode=PaymentMode.CASH)
        p3 = Payment.objects.create(member=m, amount=300, payment_mode=PaymentMode.CASH)

        assert p1.receipt_number.startswith('RCP-')
        num1 = int(p1.receipt_number.split('-')[-1])
        num2 = int(p2.receipt_number.split('-')[-1])
        num3 = int(p3.receipt_number.split('-')[-1])

        assert num2 == num1 + 1
        assert num3 == num2 + 1


@pytest.mark.django_db
class TestPDFReceiptAndNumberToWords:
    """Verifies PDF receipt generation and number to words conversion."""

    def test_number_to_words_inr_accuracy(self):
        assert number_to_words_inr(3000) == "Rupees Three Thousand Only"
        assert number_to_words_inr(Decimal('1500.50')) == "Rupees One Thousand Five Hundred and Paise Fifty Only"
        assert number_to_words_inr(100000) == "Rupees One Lakh Only"
        assert number_to_words_inr(10500000) == "Rupees One Crore Five Lakh Only"
        assert number_to_words_inr(0) == "Rupees Zero Only"

    def test_generate_receipt_pdf_bytes_and_view(self, member_with_plan, accountant_user):
        member, assignment = member_with_plan
        p = record_payment(
            member=member,
            amount=Decimal('2400.00'),
            payment_mode=PaymentMode.UPI,
            reference_number='UPI-PDF-TEST-1234',
            collected_by=accountant_user,
        )

        pdf_bytes = generate_receipt_pdf(p)
        assert isinstance(pdf_bytes, bytes)
        assert len(pdf_bytes) > 500
        # Valid PDF header
        assert pdf_bytes.startswith(b'%PDF-')

        # Test view endpoint
        client = Client()
        client.force_login(accountant_user)
        res = client.get(reverse('payments:receipt_pdf', kwargs={'payment_id': p.id}))
        assert res.status_code == 200
        assert res['Content-Type'] == 'application/pdf'
        assert f'filename="Receipt_{p.receipt_number}.pdf"' in res['Content-Disposition']
        assert res.content.startswith(b'%PDF-')


@pytest.mark.django_db
class TestPaymentPermissions:
    """Verifies role restrictions: only Accountant and Super Admin can record or cancel payments."""

    def test_viewer_denied_from_recording_and_cancelling(self, viewer_user, member_with_plan, accountant_user):
        member, assignment = member_with_plan
        p = record_payment(member=member, amount=1000, payment_mode=PaymentMode.CASH, collected_by=accountant_user)

        client = Client()
        client.force_login(viewer_user)

        # Viewer can view list and detail
        assert client.get(reverse('payments:payment_list')).status_code == 200
        assert client.get(reverse('payments:payment_detail', kwargs={'payment_id': p.id})).status_code == 200

        # Viewer is denied (HTTP 403) from recording payments
        res_record = client.get(reverse('payments:payment_record', kwargs={'member_id': member.id}))
        assert res_record.status_code == 403

        # Viewer is denied from cancelling payments
        res_cancel = client.get(reverse('payments:payment_cancel', kwargs={'payment_id': p.id}))
        assert res_cancel.status_code == 403

    def test_event_manager_denied_from_payment_operations(self, event_manager_user, member_with_plan):
        member, assignment = member_with_plan
        client = Client()
        client.force_login(event_manager_user)

        res_record = client.get(reverse('payments:payment_record', kwargs={'member_id': member.id}))
        assert res_record.status_code == 403

    def test_super_admin_can_record_and_cancel_payments(self, superadmin_user, member_with_plan):
        member, assignment = member_with_plan
        client = Client()
        client.force_login(superadmin_user)

        # Super Admin records payment
        res_record = client.post(reverse('payments:payment_record', kwargs={'member_id': member.id}), {
            'amount': '2400.00',
            'payment_date': date.today().isoformat(),
            'payment_mode': PaymentMode.UPI,
            'reference_number': 'ADMIN-UPI-001',
        })
        assert res_record.status_code == 302
        new_p = member.payments.first()
        assert new_p.amount == Decimal('2400.00')

        # Super Admin cancels payment
        res_cancel = client.post(reverse('payments:payment_cancel', kwargs={'payment_id': new_p.id}), {
            'reason': 'Cancelled by Super Admin for administrative testing.',
        })
        assert res_cancel.status_code == 302
        new_p.refresh_from_db()
        assert new_p.is_cancelled is True
