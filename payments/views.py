from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.core.paginator import Paginator
from django.core.exceptions import PermissionDenied
from django.urls import reverse
from django.http import HttpResponse

from accounts.decorators import admin_login_required, payment_management_required
from members.models import Member
from payments.models import Payment, PaymentAdjustment, PaymentStatus, PaymentMode
from payments.forms import PaymentRecordForm, PaymentCancelForm, PaymentAdjustmentForm
from payments.services import (
    calculate_member_dues,
    record_payment,
    cancel_payment,
    generate_receipt_pdf,
    sync_member_status_after_payment,
)

@admin_login_required
def payment_list_view(request):
    """
    Searchable, filterable list of all financial transactions and receipts.
    Accessible to all authenticated staff (Accountant and Super Admin have write actions).
    """
    search_query = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '').strip()
    mode_filter = request.GET.get('mode', '').strip()

    qs = Payment.objects.select_related('member', 'collected_by', 'plan_assignment__plan').all()

    if search_query:
        from core.encryption import compute_blind_index
        blind_idx = compute_blind_index(search_query)
        qs = qs.filter(
            models.Q(receipt_number__icontains=search_query) |
            models.Q(member__name__icontains=search_query) |
            models.Q(member__membership_id__iexact=search_query) |
            models.Q(member__phone_blind_index=blind_idx) |
            models.Q(reference_number__icontains=search_query)
        )

    if status_filter:
        qs = qs.filter(status=status_filter)

    if mode_filter:
        qs = qs.filter(payment_mode=mode_filter)

    paginator = Paginator(qs, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'payments/payment_list.html', {
        'page_obj': page_obj,
        'search_query': search_query,
        'status_filter': status_filter,
        'mode_filter': mode_filter,
        'status_choices': PaymentStatus.choices,
        'mode_choices': PaymentMode.choices,
        'total_count': qs.count(),
    })


@payment_management_required
def payment_record_view(request, member_id):
    """
    Records a payment for a member.
    Pre-populates outstanding due amount and automatically transitions
    member status to Active when dues are fully cleared.
    """
    member = get_object_or_404(Member, id=member_id)
    dues_info = calculate_member_dues(member)

    if request.method == 'POST':
        form = PaymentRecordForm(request.POST)
        if form.is_valid():
            amount = form.cleaned_data['amount']
            payment_date = form.cleaned_data['payment_date']
            payment_mode = form.cleaned_data['payment_mode']
            reference_number = form.cleaned_data['reference_number']
            notes = form.cleaned_data['notes']

            payment = record_payment(
                member=member,
                amount=amount,
                payment_date=payment_date,
                payment_mode=payment_mode,
                reference_number=reference_number,
                collected_by=request.user,
                notes=notes
            )

            # Auto-dispatch WhatsApp payment receipt alert (from 7039145304)
            try:
                from notifications.services import send_whatsapp_notification
                from notifications.models import NotificationTemplate
                send_whatsapp_notification(
                    member=member,
                    template_type=NotificationTemplate.PAYMENT_RECEIPT,
                    payment=payment
                )
            except Exception:
                pass

            messages.success(
                request,
                f"Payment of ₹{payment.amount:,.2f} recorded successfully. Receipt No: {payment.receipt_number}."
            )
            return redirect('payments:payment_detail', payment_id=payment.id)
    else:
        # Pre-fill with remaining due balance if any
        suggested_amount = dues_info['balance_due'] if dues_info['balance_due'] > Decimal('0.00') else ""
        form = PaymentRecordForm(initial={'amount': suggested_amount})

    return render(request, 'payments/payment_record.html', {
        'member': member,
        'form': form,
        'dues_info': dues_info,
    })


@admin_login_required
def payment_detail_view(request, payment_id):
    """Displays full transaction breakdown, linked plan assignment, audit log, and adjustments."""
    payment = get_object_or_404(
        Payment.objects.select_related('member', 'collected_by', 'cancelled_by', 'plan_assignment__plan'),
        id=payment_id
    )
    adjustments = payment.adjustments.select_related('adjusted_by').all()
    dues_info = calculate_member_dues(payment.member)

    return render(request, 'payments/payment_detail.html', {
        'payment': payment,
        'adjustments': adjustments,
        'dues_info': dues_info,
    })


@payment_management_required
def payment_cancel_view(request, payment_id):
    """
    Cancels a payment record with mandatory audit reason.
    Restores the outstanding due amount and re-evaluates member status.
    """
    payment = get_object_or_404(Payment, id=payment_id)

    if payment.is_cancelled:
        messages.warning(request, f"Payment {payment.receipt_number} is already cancelled.")
        return redirect('payments:payment_detail', payment_id=payment.id)

    if request.method == 'POST':
        form = PaymentCancelForm(request.POST)
        if form.is_valid():
            reason = form.cleaned_data['reason']
            cancel_payment(payment, user=request.user, reason=reason)
            messages.success(
                request,
                f"Payment {payment.receipt_number} has been cancelled. Member balance restored."
            )
            return redirect('payments:payment_detail', payment_id=payment.id)
    else:
        form = PaymentCancelForm()

    return render(request, 'payments/payment_cancel.html', {
        'payment': payment,
        'form': form,
    })


@payment_management_required
def payment_adjustment_view(request, payment_id):
    """Records a refund, waiver, or financial correction against a payment."""
    payment = get_object_or_404(Payment, id=payment_id)

    if payment.is_cancelled:
        messages.error(request, "Cannot record adjustments against a cancelled payment.")
        return redirect('payments:payment_detail', payment_id=payment.id)

    if request.method == 'POST':
        form = PaymentAdjustmentForm(request.POST)
        if form.is_valid():
            adj = form.save(commit=False)
            adj.payment = payment
            adj.adjusted_by = request.user
            adj.save()

            messages.success(
                request,
                f"Adjustment of ₹{adj.amount:,.2f} ({adj.get_adjustment_type_display()}) recorded."
            )
            return redirect('payments:payment_detail', payment_id=payment.id)
    else:
        form = PaymentAdjustmentForm()

    return render(request, 'payments/payment_adjustment.html', {
        'payment': payment,
        'form': form,
    })


@admin_login_required
def payment_receipt_pdf_view(request, payment_id):
    """Generates and streams the official PDF payment receipt."""
    payment = get_object_or_404(
        Payment.objects.select_related('member', 'collected_by', 'plan_assignment__plan'),
        id=payment_id
    )

    pdf_content = generate_receipt_pdf(payment)
    response = HttpResponse(pdf_content, content_type='application/pdf')
    filename = f"Receipt_{payment.receipt_number}.pdf"
    response['Content-Disposition'] = f'inline; filename="{filename}"'
    return response
