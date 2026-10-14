from datetime import timedelta
from typing import Tuple, Optional, Dict, Any
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.conf import settings

from core.encryption import normalize_phone, compute_blind_index
from members.models import Member, MemberStatus
from payments.models import Payment, PaymentStatus
from payments.services import calculate_member_dues
from portal.models import MemberOTP


def request_portal_otp(raw_phone: str) -> Tuple[bool, Optional[str], Optional[Member], Optional[str]]:
    """
    Validates mobile number, finds active member, enforces rate limiting,
    generates a 6-digit OTP, and triggers delivery.
    
    Returns:
        (success: bool, error_message: str | None, member: Member | None, raw_otp: str | None)
    """
    if not raw_phone or not raw_phone.strip():
        return False, "Please enter your registered 10-digit mobile number.", None, None

    try:
        normalized = normalize_phone(raw_phone.strip())
    except ValidationError as e:
        return False, "Invalid mobile number format. Please enter a valid 10-digit Indian mobile number.", None, None

    phone_bindex = compute_blind_index(normalized)
    member = Member.objects.active_records().filter(phone_blind_index=phone_bindex).first()

    if not member:
        return (
            False,
            "Mobile number not found in our membership records. Please ensure you are entering your registered number or contact the Institute office.",
            None,
            None
        )

    if member.status == MemberStatus.REMOVED:
        return False, "This membership record has been archived. Please contact the Institute office.", None, None

    # Rate limiting: max 4 requests per 10 minutes
    recent_requests = MemberOTP.objects.filter(
        phone_blind_index=phone_bindex,
        created_at__gte=timezone.now() - timedelta(minutes=10)
    ).count()

    if recent_requests >= 4:
        return (
            False,
            "Too many OTP requests in a short period. Please wait 10 minutes before requesting a new OTP.",
            None,
            None
        )

    # Generate cryptographically secure OTP
    raw_otp = MemberOTP.create_for_member(member, validity_minutes=5)

    # In development & testing: print to console and log
    print(f"\n=======================================================")
    print(f"  [MEMBER PORTAL OTP DELIVERY]")
    print(f"  To Member: {member.name} ({member.membership_id})")
    print(f"  Mobile:    {normalized}")
    print(f"  One-Time Password (OTP): {raw_otp}")
    print(f"  Valid for: 5 minutes")
    print(f"=======================================================\n")

    return True, None, member, raw_otp


def verify_portal_otp(member: Member, candidate_otp: str) -> Tuple[bool, str]:
    """
    Verifies the submitted candidate OTP for a member.
    Enforces expiry (5 min), single use, and attempt limits (3 attempts).
    """
    if not candidate_otp or not candidate_otp.strip():
        return False, "Please enter the 6-digit OTP received on your mobile."

    otp_record = MemberOTP.objects.filter(member=member, is_used=False).order_by('-created_at').first()

    if not otp_record:
        return False, "No active OTP request found. Please request a new OTP."

    if timezone.now() > otp_record.expires_at:
        return False, "The OTP has expired. Please request a fresh OTP."

    if otp_record.attempts >= 3:
        return False, "Maximum verification attempts exceeded. Please request a new OTP."

    is_valid = otp_record.verify(candidate_otp.strip())

    if is_valid:
        return True, "Verification successful."
    else:
        remaining = max(0, 3 - otp_record.attempts)
        if remaining > 0:
            return False, f"Incorrect OTP. {remaining} attempt{'s' if remaining > 1 else ''} remaining."
        else:
            return False, "Maximum attempts reached. This OTP is now locked. Please request a new OTP."


def mask_phone_number(raw_phone: str) -> str:
    """Masks phone number for privacy display (e.g. +91 ******3210)."""
    if not raw_phone:
        return "******"
    cleaned = raw_phone.strip()
    if len(cleaned) >= 10:
        return f"+91 ******{cleaned[-4:]}"
    return cleaned


def get_portal_dashboard_context(member: Member) -> Dict[str, Any]:
    """
    Assembles comprehensive read-only data for the Member Portal Dashboard:
    - Member profile
    - Current plan & dates
    - Financial standing & balance due
    - Completed payments & PDF download links
    - Registered family dependents
    """
    current_assignment = member.plan_assignments.filter(is_current=True).first()
    dues_info = calculate_member_dues(member)

    completed_payments = member.payments.filter(
        status=PaymentStatus.COMPLETED,
        is_cancelled=False
    ).order_by('-payment_date')

    family_members = member.family_members.all().order_by('name')

    # Grace period date
    grace_end_date = None
    if current_assignment and current_assignment.grace_period_days:
        grace_end_date = current_assignment.end_date + timedelta(days=current_assignment.grace_period_days)

    return {
        'member': member,
        'current_assignment': current_assignment,
        'grace_end_date': grace_end_date,
        'dues_info': dues_info,
        'completed_payments': completed_payments,
        'family_members': family_members,
        'masked_phone': mask_phone_number(member.phone),
        'whatsapp_sender': getattr(settings, 'WHATSAPP_SENDER_NUMBER', '7039145304'),
    }
