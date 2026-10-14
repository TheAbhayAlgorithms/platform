from decimal import Decimal
from django.db import models, transaction
from django.utils import timezone
from django.core.exceptions import ValidationError
from members.models import Member, MemberStatus
from transfers.models import Branch, InterDivisionalTransfer, TransferStatus, TransferType


def check_member_clearance(member: Member) -> dict:
    """
    Evaluates whether a railway member is clear of financial and institutional dues
    prior to issuing an inter-divisional transfer NOC.
    """
    reasons = []

    # 1. Member Status Check
    if member.status in [MemberStatus.DUE, MemberStatus.EXPIRED, MemberStatus.SUSPENDED]:
        reasons.append(f"Member status is currently '{member.get_status_display()}'.")

    # 2. Plan Assignment & Payment Dues Check
    current_assignment = getattr(member, 'plan_assignments', None)
    if current_assignment:
        active_assignment = member.plan_assignments.filter(is_current=True).first()
        if active_assignment:
            # Check completed payments for this assignment
            completed_payments = active_assignment.payments.filter(status='COMPLETED')
            total_paid = completed_payments.aggregate(total=models.Sum('amount'))['total'] or Decimal('0.00')
            if total_paid < active_assignment.final_fee:
                shortfall = active_assignment.final_fee - total_paid
                reasons.append(
                    f"Outstanding subscription fee of ₹{shortfall:,.2f} on active plan '{active_assignment.plan.name}'."
                )

    # 3. Hall Bookings Check
    if hasattr(member, 'hall_bookings'):
        unsettled_bookings = member.hall_bookings.filter(
            status__in=['CONFIRMED', 'REQUESTED'],
            payment_status__in=['PENDING', 'ADVANCE_PAID']
        )
        if unsettled_bookings.exists():
            count = unsettled_bookings.count()
            reasons.append(f"Member has {count} active or unsettled hall reservation(s).")

    is_cleared = len(reasons) == 0
    return {
        'is_cleared': is_cleared,
        'reasons': reasons,
        'summary': "All membership subscriptions and hall dues are clear." if is_cleared else "; ".join(reasons)
    }


def create_transfer_request(
    member: Member,
    from_branch: Branch,
    to_branch: Branch,
    transfer_type: str,
    transfer_order_number: str,
    transfer_order_date,
    effective_date,
    requested_by=None,
    remarks: str = ""
) -> InterDivisionalTransfer:
    """
    Initiates a new inter-divisional transfer request with automated dues verification.
    """
    if from_branch == to_branch:
        raise ValidationError("Origin branch and Destination branch cannot be identical.")

    # Check for active pending request
    if InterDivisionalTransfer.objects.filter(member=member, status=TransferStatus.PENDING).exists():
        raise ValidationError("Member already has a pending inter-divisional transfer request.")

    # Run automated clearance check
    clearance = check_member_clearance(member)

    transfer = InterDivisionalTransfer(
        member=member,
        from_branch=from_branch,
        to_branch=to_branch,
        transfer_type=transfer_type,
        transfer_order_number=transfer_order_number.strip(),
        transfer_order_date=transfer_order_date,
        effective_date=effective_date,
        dues_cleared=clearance['is_cleared'],
        dues_remarks=clearance['summary'],
        remarks=remarks.strip(),
        requested_by=requested_by,
        status=TransferStatus.PENDING
    )
    transfer.full_clean()
    transfer.save()
    return transfer


def approve_transfer_request(
    transfer: InterDivisionalTransfer,
    user,
    admin_remarks: str = "",
    force_override: bool = False
) -> InterDivisionalTransfer:
    """
    Approves an inter-divisional transfer request and issues an official digital NOC number.
    """
    if transfer.status != TransferStatus.PENDING:
        raise ValidationError(f"Only PENDING requests can be approved. Current status: {transfer.status}.")

    if not transfer.dues_cleared and not force_override:
        raise ValidationError(
            f"Cannot approve transfer with unresolved dues: {transfer.dues_remarks}. "
            "Clear dues or use authorized administrative override."
        )

    if force_override and not transfer.dues_cleared:
        transfer.dues_cleared = True
        override_note = f" [Dues clearance administratively overridden by {user.get_full_name() or user.username}]"
        transfer.dues_remarks = (transfer.dues_remarks or "") + override_note

    # Generate sequential NOC number
    if not transfer.noc_number:
        transfer.noc_number = InterDivisionalTransfer.generate_next_noc_number()
        transfer.noc_issued_at = timezone.now()

    transfer.status = TransferStatus.APPROVED
    transfer.actioned_by = user
    transfer.actioned_at = timezone.now()

    if admin_remarks.strip():
        existing = f"{transfer.remarks}\n" if transfer.remarks else ""
        transfer.remarks = f"{existing}[Approval Remarks]: {admin_remarks.strip()}"

    transfer.save()
    return transfer


def complete_transfer_request(
    transfer: InterDivisionalTransfer,
    user
) -> InterDivisionalTransfer:
    """
    Finalizes the transfer, updating the member's profile and audit logs.
    """
    if transfer.status != TransferStatus.APPROVED:
        raise ValidationError(f"Only APPROVED requests can be finalized. Current status: {transfer.status}.")

    member = transfer.member
    timestamp_str = timezone.now().strftime("%d-%m-%Y")

    if transfer.transfer_type == TransferType.OUTGOING:
        note_entry = (
            f"\n[{timestamp_str}] Inter-Divisional Transfer (Outgoing): "
            f"Relieved to {transfer.to_branch.name} [Code: {transfer.to_branch.code}] "
            f"under Order {transfer.transfer_order_number} (NOC: {transfer.noc_number})."
        )
        member.notes = (member.notes or "") + note_entry
        member.save(update_fields=['notes'])
    else:
        note_entry = (
            f"\n[{timestamp_str}] Inter-Divisional Transfer (Incoming): "
            f"Joined from {transfer.from_branch.name} [Code: {transfer.from_branch.code}] "
            f"under Order {transfer.transfer_order_number}."
        )
        member.notes = (member.notes or "") + note_entry
        if member.status in [MemberStatus.DUE, MemberStatus.EXPIRED]:
            member.status = MemberStatus.ACTIVE
        member.save(update_fields=['notes', 'status'])

    transfer.status = TransferStatus.COMPLETED
    transfer.actioned_by = user
    transfer.actioned_at = timezone.now()
    transfer.save()
    return transfer


def reject_transfer_request(
    transfer: InterDivisionalTransfer,
    user,
    rejection_reason: str
) -> InterDivisionalTransfer:
    """
    Rejects an inter-divisional transfer request with mandatory audit justification.
    """
    if transfer.status != TransferStatus.PENDING:
        raise ValidationError(f"Only PENDING requests can be rejected. Current status: {transfer.status}.")

    if not rejection_reason or not rejection_reason.strip():
        raise ValidationError("A specific reason for rejection is required.")

    transfer.status = TransferStatus.REJECTED
    transfer.rejection_reason = rejection_reason.strip()
    transfer.actioned_by = user
    transfer.actioned_at = timezone.now()
    transfer.save()
    return transfer


def cancel_transfer_request(
    transfer: InterDivisionalTransfer,
    user,
    cancel_reason: str = ""
) -> InterDivisionalTransfer:
    """
    Cancels a pending transfer request.
    """
    if transfer.status != TransferStatus.PENDING:
        raise ValidationError(f"Only PENDING requests can be cancelled. Current status: {transfer.status}.")

    transfer.status = TransferStatus.CANCELLED
    reason_note = f"Cancelled by user: {cancel_reason.strip()}" if cancel_reason.strip() else "Cancelled by user."
    transfer.rejection_reason = reason_note
    transfer.actioned_by = user
    transfer.actioned_at = timezone.now()
    transfer.save()
    return transfer
