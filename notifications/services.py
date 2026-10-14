from datetime import datetime
from typing import Dict, Any, Optional, Tuple
from django.conf import settings
from django.utils import timezone
from django.db import transaction

from core.encryption import compute_blind_index, normalize_phone
from members.models import Member
from payments.models import Payment
from payments.services import calculate_member_dues
from notifications.models import (
    WhatsAppMessageLog,
    NotificationTemplate,
    NotificationStatus,
)
from notifications.providers.base import BaseWhatsAppProvider
from notifications.providers.mock_provider import MockWhatsAppProvider
from notifications.providers.cloud_api_provider import CloudAPIWhatsAppProvider


def get_whatsapp_provider() -> BaseWhatsAppProvider:
    """Factory returning active WhatsApp provider based on application configuration."""
    provider_name = getattr(settings, 'WHATSAPP_PROVIDER', 'mock').lower()
    if provider_name == 'cloud_api':
        return CloudAPIWhatsAppProvider()
    return MockWhatsAppProvider()


# Message Template Formatters
def render_payment_receipt_message(payment: Payment) -> str:
    sender = getattr(settings, 'WHATSAPP_SENDER_NUMBER', '7039145304')
    dues_info = calculate_member_dues(payment.member)
    balance_text = f"₹{dues_info['balance_due']:,.2f}" if dues_info['balance_due'] > 0 else "NIL (All Cleared)"

    return (
        f"Namaste {payment.member.name},\n\n"
        f"Thank you for your payment to the Railway Institute.\n"
        f"Receipt No: {payment.receipt_number}\n"
        f"Amount Paid: ₹{payment.amount:,.2f}\n"
        f"Payment Mode: {payment.get_payment_mode_display()}\n"
        f"Date: {payment.payment_date:%d-%m-%Y}\n"
        f"Outstanding Balance: {balance_text}\n\n"
        f"You can view and download your official signed receipt anytime via the Member Portal: "
        f"https://railclub.local/portal/\n\n"
        f"Warm regards,\n"
        f"Accounts Section, RailClub Connect\n"
        f"Support: +91-{sender}"
    )


def render_renewal_upcoming_message(member: Member, days_remaining: int) -> str:
    sender = getattr(settings, 'WHATSAPP_SENDER_NUMBER', '7039145304')
    assignment = member.plan_assignments.filter(is_current=True).first()
    plan_name = assignment.plan.name if assignment else "Membership"
    end_date_str = f"{assignment.end_date:%d-%m-%Y}" if assignment else "soon"
    fee_str = f"₹{assignment.final_fee:,.2f}" if assignment else "standard rate"

    return (
        f"Namaste {member.name} ({member.membership_id}),\n\n"
        f"This is a gentle reminder that your Railway Institute membership ({plan_name}) "
        f"is due for renewal in {days_remaining} day{'s' if days_remaining > 1 else ''} (on {end_date_str}).\n\n"
        f"Renewal Subscription: {fee_str}\n\n"
        f"Renew your plan promptly to ensure uninterrupted access to Institute facilities, "
        f"sports complexes, and upcoming festival passes.\n\n"
        f"Member Portal: https://railclub.local/portal/\n"
        f"RailClub Connect Helpline: +91-{sender}"
    )


def render_payment_due_message(member: Member) -> str:
    sender = getattr(settings, 'WHATSAPP_SENDER_NUMBER', '7039145304')
    dues_info = calculate_member_dues(member)
    return (
        f"Namaste {member.name} ({member.membership_id}),\n\n"
        f"An outstanding subscription balance of ₹{dues_info['balance_due']:,.2f} "
        f"is pending on your Railway Institute membership ({dues_info['plan_name']}).\n\n"
        f"Please clear your pending dues at the Accounts office or online via the Member Portal.\n\n"
        f"Member Portal: https://railclub.local/portal/\n"
        f"RailClub Connect: +91-{sender}"
    )


def render_membership_expired_message(member: Member) -> str:
    sender = getattr(settings, 'WHATSAPP_SENDER_NUMBER', '7039145304')
    return (
        f"Namaste {member.name} ({member.membership_id}),\n\n"
        f"Your Railway Institute membership has expired. As a result, facility privileges "
        f"and festival celebrations access have been temporarily deactivated.\n\n"
        f"You can renew your membership immediately by contacting the Institute Office "
        f"or through your registered mobile number on our portal.\n\n"
        f"Member Portal: https://railclub.local/portal/\n"
        f"RailClub Connect: +91-{sender}"
    )


def render_otp_message(member: Member, otp_code: str) -> str:
    sender = getattr(settings, 'WHATSAPP_SENDER_NUMBER', '7039145304')
    return (
        f"Your RailClub Connect verification OTP is: {otp_code}\n\n"
        f"Valid for 5 minutes. Do not share this OTP with anyone.\n\n"
        f"- Railway Employee Institute (+91-{sender})"
    )


def send_whatsapp_notification(
    member: Member,
    template_type: str,
    custom_message: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
    payment: Optional[Payment] = None,
    otp_code: Optional[str] = None,
    days_remaining: Optional[int] = None
) -> WhatsAppMessageLog:
    """
    Central dispatcher for WhatsApp communications:
    1. Enforces DPDP consent opt-out check (member.whatsapp_opt_in).
    2. Renders template text.
    3. Records log in database.
    4. Dispatches via configured provider (Mock in dev, Cloud API in prod).
    """
    sender = getattr(settings, 'WHATSAPP_SENDER_NUMBER', '7039145304')
    provider = get_whatsapp_provider()
    provider_name = 'cloud_api' if isinstance(provider, CloudAPIWhatsAppProvider) else 'mock'

    recipient_phone = member.phone
    phone_bindex = member.phone_blind_index

    # 1. DPDP Opt-out check (except OTP authentication)
    if not member.whatsapp_opt_in and template_type != NotificationTemplate.MEMBER_PORTAL_OTP:
        log = WhatsAppMessageLog.objects.create(
            member=member,
            recipient_phone=recipient_phone,
            recipient_phone_blind_index=phone_bindex,
            template_type=template_type,
            message_body=custom_message or f"Notification skipped: Member {member.name} opted out of WhatsApp.",
            sender_number=sender,
            provider=provider_name,
            status=NotificationStatus.OPTED_OUT,
            error_message="Member has opted out of WhatsApp automated alerts (DPDP compliance)."
        )
        return log

    # 2. Render message body
    if custom_message:
        message_body = custom_message
    elif template_type == NotificationTemplate.PAYMENT_RECEIPT and payment:
        message_body = render_payment_receipt_message(payment)
    elif template_type == NotificationTemplate.RENEWAL_UPCOMING:
        message_body = render_renewal_upcoming_message(member, days_remaining or 7)
    elif template_type == NotificationTemplate.PAYMENT_DUE:
        message_body = render_payment_due_message(member)
    elif template_type == NotificationTemplate.MEMBERSHIP_EXPIRED:
        message_body = render_membership_expired_message(member)
    elif template_type == NotificationTemplate.MEMBER_PORTAL_OTP and otp_code:
        message_body = render_otp_message(member, otp_code)
    else:
        message_body = f"Notification from RailClub Connect regarding your membership ({member.membership_id})."

    # 3. Create initial pending log
    log = WhatsAppMessageLog.objects.create(
        member=member,
        recipient_phone=recipient_phone,
        recipient_phone_blind_index=phone_bindex,
        template_type=template_type,
        message_body=message_body,
        sender_number=sender,
        provider=provider_name,
        status=NotificationStatus.PENDING
    )

    # 4. Dispatch via provider
    success, wamid, error_msg = provider.send_message(
        recipient_phone=recipient_phone,
        message_text=message_body,
        template_name=template_type,
        context=context
    )

    if success:
        log.status = NotificationStatus.SENT
        log.external_message_id = wamid or ""
        log.sent_at = timezone.now()
        log.save(update_fields=['status', 'external_message_id', 'sent_at'])
    else:
        log.status = NotificationStatus.FAILED
        log.error_message = error_msg or "Unknown dispatch error"
        log.save(update_fields=['status', 'error_message'])

    return log


def process_whatsapp_webhook_payload(payload: Dict[str, Any]) -> int:
    """
    Parses Meta WhatsApp Cloud API inbound status webhooks
    and updates matching message logs.
    """
    updated_count = 0
    entries = payload.get('entry', [])

    for entry in entries:
        changes = entry.get('changes', [])
        for change in changes:
            value = change.get('value', {})
            statuses = value.get('statuses', [])

            for status_item in statuses:
                wamid = status_item.get('id')
                status_str = status_item.get('status', '').lower()
                ts_raw = status_item.get('timestamp')
                event_time = timezone.now()
                if ts_raw:
                    try:
                        event_time = timezone.make_aware(datetime.fromtimestamp(int(ts_raw)))
                    except Exception:
                        pass

                if not wamid:
                    continue

                log = WhatsAppMessageLog.objects.filter(external_message_id=wamid).first()
                if not log:
                    continue

                if status_str == 'delivered':
                    log.status = NotificationStatus.DELIVERED
                    log.delivered_at = event_time
                    log.save(update_fields=['status', 'delivered_at'])
                    updated_count += 1
                elif status_str == 'read':
                    log.status = NotificationStatus.READ
                    log.read_at = event_time
                    if not log.delivered_at:
                        log.delivered_at = event_time
                    log.save(update_fields=['status', 'read_at', 'delivered_at'])
                    updated_count += 1
                elif status_str == 'failed':
                    log.status = NotificationStatus.FAILED
                    errors = status_item.get('errors', [])
                    err_desc = errors[0].get('title', 'Delivery failed') if errors else 'Meta delivery failure'
                    log.error_message = f"Meta Webhook Error: {err_desc}"
                    log.save(update_fields=['status', 'error_message'])
                    updated_count += 1

    return updated_count
