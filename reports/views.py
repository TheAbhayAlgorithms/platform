import datetime
from decimal import Decimal
from django.shortcuts import render
from django.http import HttpResponse, HttpResponseBadRequest
from django.utils import timezone
from django.contrib import messages

from accounts.decorators import admin_login_required, payment_management_required
from accounts.models import RoleChoices
from members.models import DepartmentChoices
from reports.services import (
    get_daily_collection_data,
    get_revenue_summary_data,
    get_defaulters_data,
    get_member_demographics_data,
    export_to_excel,
    export_to_csv,
    export_to_pdf,
)


@admin_login_required
def reports_hub(request):
    """
    Central reporting hub showcasing all financial, membership,
    defaulter, and demographic reports with instant export shortcuts.
    """
    today = timezone.now().date()
    daily_stats = get_daily_collection_data(today)
    defaulters_stats = get_defaulters_data()
    demographics_stats = get_member_demographics_data()

    context = {
        'today': today,
        'daily_collection': daily_stats['total_amount'],
        'daily_count': daily_stats['total_count'],
        'defaulters_count': defaulters_stats['total_count'],
        'total_outstanding': defaulters_stats['total_outstanding'],
        'total_members': demographics_stats['total_members'],
    }
    return render(request, 'reports/hub.html', context)


@admin_login_required
def daily_collection_report(request):
    """
    Daily Financial Collection Report:
    Detailed breakdown of cash, UPI, bank transfers, cheques collected on a given day.
    Exports to Excel (.xlsx), CSV, and PDF.
    """
    date_str = request.GET.get('date', '').strip()
    if date_str:
        try:
            target_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            target_date = timezone.now().date()
    else:
        target_date = timezone.now().date()

    data = get_daily_collection_data(target_date)
    export_format = request.GET.get('export', '').lower().strip()

    if export_format in ['excel', 'csv', 'pdf']:
        headers = ["Receipt No", "Member ID", "Member Name", "Plan", "Payment Mode", "Amount (₹)", "Received By", "Time"]
        rows = []
        for p in data['payments']:
            plan_name = p.plan_assignment.plan.name if (p.plan_assignment and p.plan_assignment.plan) else "-"
            received_by_name = p.collected_by.get_full_name() or p.collected_by.username if p.collected_by else "System"
            rows.append([

                p.receipt_number,
                p.member.membership_id,
                p.member.name,
                plan_name,
                p.get_payment_mode_display(),
                float(p.amount),
                received_by_name,
                p.created_at.strftime("%H:%M")
            ])

        summary_metrics = {
            "Collection Date": target_date.strftime("%d-%m-%Y"),
            "Total Transactions": data['total_count'],
            "Gross Collection": f"₹{data['total_amount']:,.2f}",
            "Adjustments / Refunds": f"₹{data['adjustments']:,.2f}",
            "Net Collection": f"₹{data['net_collection']:,.2f}",
        }

        filename_base = f"daily_collection_{target_date.strftime('%Y%m%d')}"

        if export_format == 'excel':
            excel_bytes = export_to_excel(
                report_title=f"Daily Collection Report ({target_date:%d-%m-%Y})",
                headers=headers,
                rows=rows,
                summary_metrics=summary_metrics
            )
            response = HttpResponse(
                excel_bytes,
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
            response['Content-Disposition'] = f'attachment; filename="{filename_base}.xlsx"'
            return response

        elif export_format == 'csv':
            csv_content = export_to_csv(headers, rows)
            response = HttpResponse(csv_content, content_type='text/csv; charset=utf-8')
            response['Content-Disposition'] = f'attachment; filename="{filename_base}.csv"'
            return response

        elif export_format == 'pdf':
            pdf_bytes = export_to_pdf(
                report_title=f"Daily Collection Report ({target_date:%d-%m-%Y})",
                headers=headers,
                rows=rows,
                summary_metrics=summary_metrics,
                orientation='landscape'
            )
            response = HttpResponse(pdf_bytes, content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="{filename_base}.pdf"'
            return response

    context = {
        'target_date': target_date,
        'data': data,
    }
    return render(request, 'reports/daily_collection.html', context)


@admin_login_required
def revenue_summary_report(request):
    """
    Date-Range Revenue Report:
    Aggregated income analytics over custom date intervals, broken down by mode & plan.
    Exports to Excel (.xlsx), CSV, and PDF.
    """
    today = timezone.now().date()
    start_str = request.GET.get('start_date', '').strip()
    end_str = request.GET.get('end_date', '').strip()

    if start_str:
        try:
            start_date = datetime.datetime.strptime(start_str, '%Y-%m-%d').date()
        except ValueError:
            start_date = today - datetime.timedelta(days=30)
    else:
        start_date = today - datetime.timedelta(days=30)

    if end_str:
        try:
            end_date = datetime.datetime.strptime(end_str, '%Y-%m-%d').date()
        except ValueError:
            end_date = today
    else:
        end_date = today

    if start_date > end_date:
        start_date, end_date = end_date, start_date

    data = get_revenue_summary_data(start_date, end_date)
    export_format = request.GET.get('export', '').lower().strip()

    if export_format in ['excel', 'csv', 'pdf']:
        headers = ["Date", "Receipt No", "Member ID", "Member Name", "Plan", "Payment Mode", "Amount (₹)"]
        rows = []
        for p in data['payments']:
            plan_name = p.plan_assignment.plan.name if (p.plan_assignment and p.plan_assignment.plan) else "-"
            rows.append([
                p.payment_date.strftime("%d-%m-%Y"),
                p.receipt_number,
                p.member.membership_id,
                p.member.name,
                plan_name,
                p.get_payment_mode_display(),
                float(p.amount)
            ])

        summary_metrics = {
            "Period": f"{start_date:%d-%m-%Y} to {end_date:%d-%m-%Y}",
            "Total Transactions": data['total_transactions'],
            "Gross Revenue": f"₹{data['total_revenue']:,.2f}",
            "Adjustments / Refunds": f"₹{data['adjustments']:,.2f}",
            "Net Revenue": f"₹{data['net_revenue']:,.2f}",
        }

        filename_base = f"revenue_report_{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}"

        if export_format == 'excel':
            excel_bytes = export_to_excel(
                report_title=f"Revenue Summary ({start_date:%d-%m-%Y} to {end_date:%d-%m-%Y})",
                headers=headers,
                rows=rows,
                summary_metrics=summary_metrics
            )
            response = HttpResponse(
                excel_bytes,
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
            response['Content-Disposition'] = f'attachment; filename="{filename_base}.xlsx"'
            return response

        elif export_format == 'csv':
            csv_content = export_to_csv(headers, rows)
            response = HttpResponse(csv_content, content_type='text/csv; charset=utf-8')
            response['Content-Disposition'] = f'attachment; filename="{filename_base}.csv"'
            return response

        elif export_format == 'pdf':
            pdf_bytes = export_to_pdf(
                report_title=f"Revenue Summary ({start_date:%d-%m-%Y} to {end_date:%d-%m-%Y})",
                headers=headers,
                rows=rows,
                summary_metrics=summary_metrics,
                orientation='landscape'
            )
            response = HttpResponse(pdf_bytes, content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="{filename_base}.pdf"'
            return response

    context = {
        'start_date': start_date,
        'end_date': end_date,
        'data': data,
    }
    return render(request, 'reports/revenue_summary.html', context)


@admin_login_required
def defaulters_report(request):
    """
    Outstanding Dues & Defaulters Aging Report:
    Lists members with pending subscription fees or expired plans with balances due.
    Exports to Excel (.xlsx), CSV, and PDF.
    """
    dept_filter = request.GET.get('department', '').strip() or None
    data = get_defaulters_data(department=dept_filter)
    export_format = request.GET.get('export', '').lower().strip()

    if export_format in ['excel', 'csv', 'pdf']:
        headers = ["Member ID", "Name", "Phone", "Department", "Status", "Plan", "Expiry Date", "Days Overdue", "Total Due (₹)", "Paid (₹)", "Balance (₹)"]
        rows = []
        for d in data['defaulters']:
            expiry_str = d['end_date'].strftime("%d-%m-%Y") if d['end_date'] else "-"
            rows.append([
                d['membership_id'],
                d['name'],
                d['phone'],
                d['department'],
                d['status'],
                d['plan_name'],
                expiry_str,
                d['days_overdue'],
                float(d['total_due']),
                float(d['total_paid']),
                float(d['balance_due'])
            ])

        summary_metrics = {
            "Report Date": timezone.now().strftime("%d-%m-%Y"),
            "Total Defaulters": data['total_count'],
            "Total Outstanding Dues": f"₹{data['total_outstanding']:,.2f}",
            "Department Filter": dept_filter or "All Departments",
        }

        filename_base = f"defaulters_report_{timezone.now().strftime('%Y%m%d')}"

        if export_format == 'excel':
            excel_bytes = export_to_excel(
                report_title="Outstanding Dues & Defaulters Report",
                headers=headers,
                rows=rows,
                summary_metrics=summary_metrics
            )
            response = HttpResponse(
                excel_bytes,
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
            response['Content-Disposition'] = f'attachment; filename="{filename_base}.xlsx"'
            return response

        elif export_format == 'csv':
            csv_content = export_to_csv(headers, rows)
            response = HttpResponse(csv_content, content_type='text/csv; charset=utf-8')
            response['Content-Disposition'] = f'attachment; filename="{filename_base}.csv"'
            return response

        elif export_format == 'pdf':
            pdf_bytes = export_to_pdf(
                report_title="Outstanding Dues & Defaulters Report",
                headers=headers,
                rows=rows,
                summary_metrics=summary_metrics,
                orientation='landscape'
            )
            response = HttpResponse(pdf_bytes, content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="{filename_base}.pdf"'
            return response

    context = {
        'data': data,
        'department_filter': dept_filter,
    }
    return render(request, 'reports/defaulters.html', context)


@admin_login_required
def member_demographics_report(request):
    """
    Member Directory & Demographics Analytics:
    Breakdown by Railway Department, Membership Status, and Active Plan Subscriptions.
    Exports to Excel (.xlsx) and CSV.
    """
    data = get_member_demographics_data()
    export_format = request.GET.get('export', '').lower().strip()

    if export_format in ['excel', 'csv']:
        headers = ["Department", "Active Member Count"]
        rows = [[dept, count] for dept, count in data['dept_counts'].items()]

        summary_metrics = {
            "Total Active Members": data['total_members'],
            "Members with Current Plan": data['with_plan_count'],
            "Members without Active Plan": data['without_plan_count'],
            "WhatsApp Opted-In (DPDP)": data['opt_in_count'],
        }

        filename_base = f"member_demographics_{timezone.now().strftime('%Y%m%d')}"

        if export_format == 'excel':
            excel_bytes = export_to_excel(
                report_title="Member Demographics by Department",
                headers=headers,
                rows=rows,
                summary_metrics=summary_metrics
            )
            response = HttpResponse(
                excel_bytes,
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
            response['Content-Disposition'] = f'attachment; filename="{filename_base}.xlsx"'
            return response

        elif export_format == 'csv':
            csv_content = export_to_csv(headers, rows)
            response = HttpResponse(csv_content, content_type='text/csv; charset=utf-8')
            response['Content-Disposition'] = f'attachment; filename="{filename_base}.csv"'
            return response

    context = {
        'data': data,
    }
    return render(request, 'reports/demographics.html', context)
