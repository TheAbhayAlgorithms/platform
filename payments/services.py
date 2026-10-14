import io
from decimal import Decimal
from typing import Dict, Any
from django.db import transaction
from django.utils import timezone
from django.conf import settings
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

from members.models import Member, MemberStatus
from plans.models import MemberPlanAssignment
from payments.models import Payment, PaymentStatus, PaymentMode
from core.utils import number_to_words_inr

def calculate_member_dues(member: Member) -> Dict[str, Any]:
    """
    Calculates comprehensive financial dues and payment breakdown for a member.
    Handles partial payments, overpayments, late fees, and running balance.
    """
    current_assignment = member.plan_assignments.filter(is_current=True).first()

    if not current_assignment:
        # Check all non-cancelled payments made by member
        total_paid = member.payments.filter(
            status=PaymentStatus.COMPLETED,
            is_cancelled=False
        ).aggregate(total=models.Sum('amount'))['total'] or Decimal('0.00')

        return {
            'has_plan': False,
            'plan_assignment': None,
            'plan_name': 'No Plan Assigned',
            'base_fee': Decimal('0.00'),
            'late_fee': Decimal('0.00'),
            'total_due': Decimal('0.00'),
            'total_paid': total_paid,
            'balance_due': Decimal('0.00'),
            'excess_paid': total_paid,
            'is_fully_paid': True,
        }

    base_fee = current_assignment.final_fee
    late_fee = current_assignment.current_late_fee
    total_due = base_fee + late_fee

    # Calculate completed payments for this assignment
    completed_payments = member.payments.filter(
        status=PaymentStatus.COMPLETED,
        is_cancelled=False,
        plan_assignment=current_assignment
    )
    total_paid = sum((p.amount for p in completed_payments), Decimal('0.00'))

    if total_paid >= total_due:
        balance_due = Decimal('0.00')
        excess_paid = total_paid - total_due
        is_fully_paid = True
    else:
        balance_due = total_due - total_paid
        excess_paid = Decimal('0.00')
        is_fully_paid = False

    return {
        'has_plan': True,
        'plan_assignment': current_assignment,
        'plan_name': current_assignment.plan.name,
        'start_date': current_assignment.start_date,
        'end_date': current_assignment.end_date,
        'base_fee': base_fee,
        'late_fee': late_fee,
        'total_due': total_due,
        'total_paid': total_paid,
        'balance_due': balance_due,
        'excess_paid': excess_paid,
        'is_fully_paid': is_fully_paid,
    }


def sync_member_status_after_payment(member: Member):
    """
    Auto-updates member status based on current payment balance.
    - If fully paid (balance_due == 0) and status was DUE -> set ACTIVE.
    - If outstanding balance (balance_due > 0) and status was ACTIVE -> set DUE.
    Preserves REMOVED and SUSPENDED states.
    """
    if member.status in [MemberStatus.REMOVED, MemberStatus.SUSPENDED]:
        return

    dues_info = calculate_member_dues(member)

    if dues_info['is_fully_paid']:
        if member.status == MemberStatus.DUE:
            member.status = MemberStatus.ACTIVE
            member.save(update_fields=['status', 'updated_at'])
    else:
        if member.status == MemberStatus.ACTIVE:
            member.status = MemberStatus.DUE
            member.save(update_fields=['status', 'updated_at'])


def record_payment(
    member: Member,
    amount: Decimal,
    payment_mode: str,
    payment_date=None,
    reference_number: str = "",
    collected_by=None,
    notes: str = ""
) -> Payment:
    """
    Records a payment, links to current plan assignment, generates sequential receipt,
    and auto-updates member status.
    """
    if payment_date is None:
        payment_date = timezone.now().date()

    current_assignment = member.plan_assignments.filter(is_current=True).first()

    with transaction.atomic():
        payment = Payment.objects.create(
            member=member,
            plan_assignment=current_assignment,
            amount=amount,
            payment_date=payment_date,
            payment_mode=payment_mode,
            reference_number=reference_number,
            collected_by=collected_by,
            notes=notes,
            status=PaymentStatus.COMPLETED,
        )

        # Sync member status
        sync_member_status_after_payment(member)

        return payment


def cancel_payment(payment: Payment, user, reason: str) -> Payment:
    """
    Cancels a payment record, keeping audit trail, and reverts member status if dues are restored.
    """
    with transaction.atomic():
        payment.cancel(user=user, reason=reason)
        sync_member_status_after_payment(payment.member)
        return payment


def generate_receipt_pdf(payment: Payment) -> bytes:
    """
    Generates a printable, professional PDF receipt with ReportLab.
    Includes institute branding, receipt number, member details, payment breakdown,
    and amount in words.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=40,
        leftMargin=40,
        topMargin=40,
        bottomMargin=40
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontSize=18,
        leading=22,
        alignment=1,  # Center
        textColor=colors.HexColor('#1f2937'),
        fontName='Helvetica-Bold'
    )
    subtitle_style = ParagraphStyle(
        'DocSub',
        parent=styles['Normal'],
        fontSize=10,
        leading=14,
        alignment=1,
        textColor=colors.HexColor('#4b5563'),
        fontName='Helvetica'
    )
    receipt_header_style = ParagraphStyle(
        'ReceiptHeader',
        parent=styles['Normal'],
        fontSize=12,
        leading=16,
        alignment=1,
        textColor=colors.HexColor('#111827'),
        fontName='Helvetica-Bold'
    )
    normal_style = styles['Normal']
    normal_bold = ParagraphStyle('NBold', parent=normal_style, fontName='Helvetica-Bold')

    elements = []

    # 1. Header
    institute_name = getattr(settings, 'INSTITUTE_NAME', 'RailClub Connect')
    elements.append(Paragraph(f"<b>{institute_name}</b>", title_style))
    elements.append(Paragraph("Railway Employees Welfare & Cultural Institute", subtitle_style))
    elements.append(Paragraph("Western & Central Railway Staff Welfare Association", subtitle_style))
    elements.append(Spacer(1, 10))
    elements.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#1f2937')))
    elements.append(Spacer(1, 10))

    # 2. Receipt Title & Metadata
    elements.append(Paragraph("<b>OFFICIAL PAYMENT RECEIPT</b>", receipt_header_style))
    if payment.is_cancelled:
        elements.append(Spacer(1, 5))
        cancelled_style = ParagraphStyle('CanStyle', parent=title_style, fontSize=14, textColor=colors.red)
        elements.append(Paragraph("*** CANCELLED RECEIPT ***", cancelled_style))

    elements.append(Spacer(1, 15))

    meta_table_data = [
        [
            Paragraph(f"<b>Receipt No:</b> {payment.receipt_number}", normal_style),
            Paragraph(f"<b>Date:</b> {payment.payment_date.strftime('%d-%m-%Y')}", normal_style)
        ],
        [
            Paragraph(f"<b>Payment Mode:</b> {payment.get_payment_mode_display()}", normal_style),
            Paragraph(f"<b>Ref / Transaction ID:</b> {payment.reference_number or 'N/A'}", normal_style)
        ],
    ]
    meta_table = Table(meta_table_data, colWidths=[270, 260])
    meta_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
    ]))
    elements.append(meta_table)
    elements.append(Spacer(1, 12))

    # 3. Member Details Section
    elements.append(Paragraph("<b>Member Details:</b>", normal_bold))
    elements.append(Spacer(1, 5))

    member_data = [
        [Paragraph("<b>Full Name:</b>", normal_style), Paragraph(payment.member.name, normal_style)],
        [Paragraph("<b>Membership ID:</b>", normal_style), Paragraph(payment.member.membership_id, normal_style)],
        [Paragraph("<b>Railway Employee ID:</b>", normal_style), Paragraph(payment.member.employee_id or 'N/A', normal_style)],
        [Paragraph("<b>Department:</b>", normal_style), Paragraph(payment.member.get_department_display(), normal_style)],
        [Paragraph("<b>Contact Phone:</b>", normal_style), Paragraph(payment.member.phone, normal_style)],
    ]
    member_table = Table(member_data, colWidths=[150, 380])
    member_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f9fafb')),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#d1d5db')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e5e7eb')),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    elements.append(member_table)
    elements.append(Spacer(1, 15))

    # 4. Payment Items Table
    plan_name = payment.plan_assignment.plan.name if payment.plan_assignment else "Membership Contribution / Festival Dues"
    validity_info = ""
    if payment.plan_assignment:
        validity_info = f" (Validity: {payment.plan_assignment.start_date.strftime('%d-%m-%Y')} to {payment.plan_assignment.end_date.strftime('%d-%m-%Y')})"

    item_data = [
        [Paragraph("<b>Description</b>", normal_bold), Paragraph("<b>Amount (INR)</b>", normal_bold)],
        [Paragraph(f"{plan_name}{validity_info}", normal_style), Paragraph(f"₹ {payment.amount:,.2f}", normal_style)],
        [Paragraph("<b>Total Received:</b>", normal_bold), Paragraph(f"<b>₹ {payment.amount:,.2f}</b>", normal_bold)],
    ]
    item_table = Table(item_data, colWidths=[380, 150])
    item_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f3f4f6')),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#1f2937')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#d1d5db')),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    elements.append(item_table)
    elements.append(Spacer(1, 12))

    # 5. Amount in Words
    words_str = number_to_words_inr(payment.amount)
    elements.append(Paragraph(f"<b>Amount in Words:</b> <i>{words_str}</i>", normal_style))
    elements.append(Spacer(1, 20))

    # 6. Footer & Signatory
    collector_name = payment.collected_by.get_full_name() if payment.collected_by else "Authorized Staff"
    footer_data = [
        [
            Paragraph(f"<b>Collected By:</b> {collector_name}", normal_style),
            Paragraph("<b>For RailClub Connect</b><br/><br/><br/>Authorized Signatory", ParagraphStyle('Sig', parent=normal_style, alignment=2))
        ]
    ]
    footer_table = Table(footer_data, colWidths=[260, 270])
    footer_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    elements.append(footer_table)
    elements.append(Spacer(1, 25))

    elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor('#d1d5db')))
    elements.append(Spacer(1, 5))
    elements.append(Paragraph(
        "This is a computer-generated official receipt issued by RailClub Connect. No physical signature is required.",
        ParagraphStyle('Disclaimer', parent=subtitle_style, fontSize=8, alignment=1)
    ))

    doc.build(elements)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
