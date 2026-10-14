from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import HttpResponse, HttpResponseForbidden
from django.views.decorators.http import require_POST
from django.urls import reverse
from django.core.exceptions import PermissionDenied
from django.conf import settings

from members.models import Member
from payments.models import Payment, PaymentStatus
from payments.services import generate_receipt_pdf
from portal.forms import MemberPhoneLoginForm, MemberOTPVerifyForm
from portal.decorators import member_login_required
from portal.services import (
    request_portal_otp,
    verify_portal_otp,
    get_portal_dashboard_context,
    mask_phone_number,
)


def member_login(request):
    """
    Landing page for Member Self-Service Portal.
    Accepts 10-digit registered Indian mobile number and sends OTP.
    """
    if request.session.get('member_authenticated') and request.session.get('member_id'):
        return redirect('portal:dashboard')

    if request.method == 'POST':
        form = MemberPhoneLoginForm(request.POST)
        if form.is_valid():
            normalized_phone = form.cleaned_data['phone']
            success, error_msg, member, raw_otp = request_portal_otp(normalized_phone)

            if success:
                request.session['pending_member_id'] = member.id
                request.session['pending_masked_phone'] = mask_phone_number(member.phone)
                request.session['demo_otp'] = raw_otp
                messages.info(
                    request,
                    f"A 6-digit OTP has been sent to your registered mobile number "
                    f"({mask_phone_number(member.phone)}). Valid for 5 minutes."
                )
                return redirect('portal:verify_otp')
            else:
                messages.error(request, error_msg)
    else:
        form = MemberPhoneLoginForm()

    return render(request, 'portal/login.html', {'form': form})


def member_verify_otp(request):
    """
    Verifies the 6-digit OTP for the pending member.
    Enforces maximum attempts and expiry.
    """
    if request.session.get('member_authenticated') and request.session.get('member_id'):
        return redirect('portal:dashboard')

    pending_member_id = request.session.get('pending_member_id')
    if not pending_member_id:
        messages.warning(request, "Please start by entering your registered mobile number.")
        return redirect('portal:login')

    member = Member.objects.active_records().filter(pk=pending_member_id).first()
    if not member:
        request.session.pop('pending_member_id', None)
        request.session.pop('pending_masked_phone', None)
        messages.error(request, "Member session expired. Please enter your mobile number again.")
        return redirect('portal:login')

    masked_phone = request.session.get('pending_masked_phone', mask_phone_number(member.phone))

    if request.method == 'POST':
        form = MemberOTPVerifyForm(request.POST)
        if form.is_valid():
            candidate_otp = form.cleaned_data['otp']
            is_valid, msg = verify_portal_otp(member, candidate_otp)

            if is_valid:
                # Set authenticated member portal session
                request.session['member_authenticated'] = True
                request.session['member_id'] = member.id
                request.session.pop('pending_member_id', None)
                request.session.pop('pending_masked_phone', None)
                request.session.pop('demo_otp', None)

                messages.success(request, f"Welcome to RailClub Connect, {member.name}!")
                return redirect('portal:dashboard')
            else:
                messages.error(request, msg)
    else:
        form = MemberOTPVerifyForm()

    demo_otp = request.session.get('demo_otp') if (getattr(settings, 'WHATSAPP_PROVIDER', 'mock') == 'mock' or settings.DEBUG) else None

    context = {
        'form': form,
        'member': member,
        'masked_phone': masked_phone,
        'demo_otp': demo_otp,
    }
    return render(request, 'portal/verify_otp.html', context)


@require_POST
def member_resend_otp(request):
    """
    Resends OTP to the pending member with rate-limit protection.
    """
    pending_member_id = request.session.get('pending_member_id')
    if not pending_member_id:
        messages.warning(request, "Please enter your mobile number to receive an OTP.")
        return redirect('portal:login')

    member = Member.objects.active_records().filter(pk=pending_member_id).first()
    if not member:
        messages.error(request, "Member record not found. Please log in again.")
        return redirect('portal:login')

    success, error_msg, _, raw_otp = request_portal_otp(member.phone)
    if success:
        request.session['demo_otp'] = raw_otp
        messages.success(request, "A fresh OTP has been sent to your registered mobile number.")
    else:
        messages.error(request, error_msg)

    return redirect('portal:verify_otp')


@member_login_required
def member_dashboard(request):
    """
    Member Portal Dashboard:
    Read-only view showing current membership status, plan validity,
    dues, transaction receipts, and family dependents.
    """
    member = request.portal_member
    context = get_portal_dashboard_context(member)
    return render(request, 'portal/dashboard.html', context)


@member_login_required
def member_download_receipt(request, payment_id):
    """
    Secure PDF receipt download endpoint for members.
    Enforces IDOR authorization: members can ONLY access receipts belonging to themselves!
    """
    member = request.portal_member
    payment = get_object_or_404(
        Payment,
        pk=payment_id,
        member=member,
        is_cancelled=False,
        status=PaymentStatus.COMPLETED
    )

    pdf_content = generate_receipt_pdf(payment)
    response = HttpResponse(pdf_content, content_type='application/pdf')
    filename = f"Receipt_{payment.receipt_number}.pdf"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@member_login_required
def member_view_noc(request, transfer_id):
    """
    Allows a verified member to view and print their own official NOC Certificate.
    Strictly verifies ownership to prevent IDOR vulnerabilities.
    """
    from transfers.models import InterDivisionalTransfer, Branch
    from django.utils import timezone
    member = request.portal_member
    transfer = get_object_or_404(
        InterDivisionalTransfer.objects.select_related('member', 'from_branch', 'to_branch', 'actioned_by'),
        transfer_id=transfer_id,
        member=member
    )
    if not transfer.noc_number:
        messages.error(request, "No Objection Certificate has not yet been issued for this transfer.")
        return redirect('portal:dashboard')

    home_branch = Branch.objects.filter(is_home_branch=True).first()
    context = {
        'transfer': transfer,
        'home_branch': home_branch,
        'printed_at': timezone.now(),
    }
    return render(request, 'transfers/transfer_noc.html', context)



def member_logout(request):
    """
    Logs out the member from the self-service portal.
    Flushes member-specific session keys.
    """
    request.session.pop('member_authenticated', None)
    request.session.pop('member_id', None)
    request.session.pop('pending_member_id', None)
    request.session.pop('pending_masked_phone', None)
    messages.info(request, "You have been logged out of the Member Portal.")
    return redirect('portal:login')
