from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, Any, Optional, List
from django.db import transaction, models
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User

from members.models import Member, MemberStatus
from notifications.models import NotificationTemplate
from notifications.services import send_whatsapp_notification
from bookings.models import (
    Facility,
    HallBooking,
    BookingSlot,
    BookingStatus,
    PaymentStatus,
    EventType,
)


def check_facility_availability(
    facility: Facility,
    booking_date: date,
    slot: str,
    exclude_booking_id: Optional[int] = None
) -> bool:
    """
    Checks whether a specific facility is available on the given date and slot.
    Active bookings (REQUESTED or CONFIRMED) block overlapping slots:
    - FULL_DAY blocks all slots (MORNING, EVENING, FULL_DAY).
    - MORNING blocks MORNING and FULL_DAY.
    - EVENING blocks EVENING and FULL_DAY.
    """
    active_statuses = [BookingStatus.REQUESTED, BookingStatus.CONFIRMED]

    existing_bookings = HallBooking.objects.filter(
        facility=facility,
        booking_date=booking_date,
        status__in=active_statuses
    )

    if exclude_booking_id:
        existing_bookings = existing_bookings.exclude(pk=exclude_booking_id)

    if not existing_bookings.exists():
        return True

    # If requested is FULL_DAY, any existing active booking conflicts
    if slot == BookingSlot.FULL_DAY:
        return False

    # If requested is MORNING, conflicts if any existing is MORNING or FULL_DAY
    if slot == BookingSlot.MORNING:
        conflict = existing_bookings.filter(
            slot__in=[BookingSlot.MORNING, BookingSlot.FULL_DAY]
        ).exists()
        return not conflict

    # If requested is EVENING, conflicts if any existing is EVENING or FULL_DAY
    if slot == BookingSlot.EVENING:
        conflict = existing_bookings.filter(
            slot__in=[BookingSlot.EVENING, BookingSlot.FULL_DAY]
        ).exists()
        return not conflict

    return False


def create_hall_booking(
    facility: Facility,
    member: Member,
    booking_date: date,
    slot: str,
    event_type: str,
    purpose: str,
    special_requests: str = '',
    advance_paid: Decimal = Decimal('0.00'),
    is_staff_confirmed: bool = True,
    approved_by: Optional[User] = None
) -> HallBooking:
    """
    Validates and reserves a facility for a member function.
    Calculates rent, security deposit, electricity fees, and sends WhatsApp confirmation.
    """
    if member.is_removed:
        raise ValidationError("Cannot create booking for a removed member record.")

    if member.status == MemberStatus.SUSPENDED:
        raise ValidationError("Member is currently suspended. Institute hall bookings are barred.")

    if not facility.is_active:
        raise ValidationError(f"Facility '{facility.name}' is currently deactivated for maintenance.")

    today = timezone.now().date()
    if booking_date < today:
        raise ValidationError("Cannot book facilities for past dates.")

    with transaction.atomic():
        # Concurrency safety check
        is_available = check_facility_availability(facility, booking_date, slot)
        if not is_available:
            raise ValidationError(
                f"Facility '{facility.name}' is already reserved for {booking_date:%d-%m-%Y} ({slot})."
            )

        rent = facility.full_day_rent if slot == BookingSlot.FULL_DAY else facility.rent_per_slot
        deposit = facility.security_deposit
        electricity = facility.flat_electricity_charge
        total = rent + deposit + electricity

        if advance_paid > total:
            raise ValidationError(f"Advance payment (₹{advance_paid}) cannot exceed grand total (₹{total}).")

        # Payment status
        if advance_paid >= total:
            pay_status = PaymentStatus.FULLY_PAID
        elif advance_paid > Decimal('0.00'):
            pay_status = PaymentStatus.ADVANCE_PAID
        else:
            pay_status = PaymentStatus.PENDING

        initial_status = BookingStatus.CONFIRMED if is_staff_confirmed else BookingStatus.REQUESTED

        booking = HallBooking.objects.create(
            facility=facility,
            member=member,
            event_type=event_type,
            purpose=purpose.strip(),
            booking_date=booking_date,
            slot=slot,
            rent_amount=rent,
            deposit_amount=deposit,
            electricity_charges=electricity,
            total_amount=total,
            advance_paid=advance_paid,
            status=initial_status,
            payment_status=pay_status,
            special_requests=special_requests.strip() if special_requests else '',
            approved_by=approved_by if is_staff_confirmed else None
        )

        # Automated WhatsApp confirmation
        if member.whatsapp_opt_in:
            status_desc = "Confirmed & Reserved" if is_staff_confirmed else "Request Received (Pending Review)"
            msg = (
                f"Namaste {member.name},\n\n"
                f"Your Hall Reservation ({booking.booking_id}) has been {status_desc}!\n\n"
                f"Facility: {facility.name}\n"
                f"Function: {booking.purpose}\n"
                f"Date: {booking_date:%d-%m-%Y}\n"
                f"Slot: {booking.get_slot_display()}\n\n"
                f"Rent: ₹{rent:,.2f}\n"
                f"Security Deposit (Refundable): ₹{deposit:,.2f}\n"
                f"Electricity/Generator: ₹{electricity:,.2f}\n"
                f"Grand Total: ₹{total:,.2f}\n"
                f"Advance Paid: ₹{advance_paid:,.2f}\n"
                f"Balance Due: ₹{booking.balance_amount:,.2f}\n\n"
                f"Please ensure balance payment is completed prior to key handover.\n"
                f"Helpline: 7039145304"
            )
            send_whatsapp_notification(
                member=member,
                template_type=NotificationTemplate.CUSTOM,
                custom_message=msg
            )

        return booking


def approve_hall_booking(booking: HallBooking, user: User) -> HallBooking:
    """Approves a pending hall booking request."""
    # Verify no conflicting booking was created in the interim
    is_available = check_facility_availability(
        booking.facility,
        booking.booking_date,
        booking.slot,
        exclude_booking_id=booking.id
    )
    if not is_available:
        raise ValidationError("Cannot approve: another confirmed booking now conflicts with this slot.")

    booking.status = BookingStatus.CONFIRMED
    booking.approved_by = user
    booking.save(update_fields=['status', 'approved_by', 'updated_at'])

    if booking.member.whatsapp_opt_in:
        msg = (
            f"Namaste {booking.member.name},\n\n"
            f"Good news! Your reservation request for {booking.facility.name} "
            f"({booking.booking_id}) on {booking.booking_date:%d-%m-%Y} has been APPROVED by the Institute Office.\n\n"
            f"Slot: {booking.get_slot_display()}\n"
            f"Total Payable: ₹{booking.total_amount:,.2f}\n"
            f"Balance Due: ₹{booking.balance_amount:,.2f}\n\n"
            f"Helpline: 7039145304"
        )
        send_whatsapp_notification(
            member=booking.member,
            template_type=NotificationTemplate.CUSTOM,
            custom_message=msg
        )

    return booking


def cancel_hall_booking(booking: HallBooking, reason: str = '', user: Optional[User] = None) -> HallBooking:
    """Cancels a hall booking, freeing the slot for other members."""
    booking.status = BookingStatus.CANCELLED
    if reason:
        booking.cancellation_reason = reason.strip()
    booking.save(update_fields=['status', 'cancellation_reason', 'updated_at'])

    if booking.member.whatsapp_opt_in:
        msg = (
            f"Namaste {booking.member.name},\n\n"
            f"Your reservation for {booking.facility.name} on {booking.booking_date:%d-%m-%Y} "
            f"({booking.booking_id}) has been CANCELLED.\n"
        )
        if reason:
            msg += f"Reason: {reason}\n"
        msg += "\nFor deposit refunds or inquiries, please contact the Institute Office.\nHelpline: 7039145304"

        send_whatsapp_notification(
            member=booking.member,
            template_type=NotificationTemplate.CUSTOM,
            custom_message=msg
        )

    return booking


def refund_security_deposit(
    booking: HallBooking,
    refund_amount: Decimal,
    user: Optional[User] = None
) -> HallBooking:
    """Records the refund of the security deposit following event inspection."""
    if refund_amount < Decimal('0.00') or refund_amount > booking.deposit_amount:
        raise ValidationError(
            f"Refund amount must be between ₹0.00 and the deposited ₹{booking.deposit_amount:,.2f}."
        )

    booking.deposit_refunded = True
    booking.deposit_refund_amount = refund_amount
    booking.deposit_refund_date = timezone.now().date()
    booking.status = BookingStatus.COMPLETED if booking.status == BookingStatus.CONFIRMED else booking.status
    booking.save(update_fields=['deposit_refunded', 'deposit_refund_amount', 'deposit_refund_date', 'status', 'updated_at'])

    return booking
