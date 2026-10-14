from datetime import date, datetime
from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.core.paginator import Paginator
from django.core.exceptions import ValidationError
from django.http import HttpResponse, HttpResponseForbidden
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.db import models

from accounts.decorators import admin_login_required, event_management_required
from accounts.models import RoleChoices
from members.models import Member, MemberStatus
from portal.decorators import member_login_required
from bookings.models import (
    Facility,
    HallBooking,
    BookingSlot,
    BookingStatus,
    PaymentStatus,
    EventType,
)
from bookings.forms import (
    FacilityForm,
    StaffHallBookingForm,
    MemberPortalBookingForm,
    DepositRefundForm,
)
from bookings.services import (
    check_facility_availability,
    create_hall_booking,
    approve_hall_booking,
    cancel_hall_booking,
    refund_security_deposit,
)


@admin_login_required
def booking_list(request):
    """
    Staff dashboard listing all wedding, reception, and hall reservations.
    Filterable by facility, status, slot, and member search.
    """
    status_filter = request.GET.get('status', '').strip()
    facility_filter = request.GET.get('facility', '').strip()
    search_query = request.GET.get('q', '').strip()

    bookings_qs = HallBooking.objects.select_related('facility', 'member', 'approved_by').order_by('-booking_date', '-booked_at')

    if status_filter:
        bookings_qs = bookings_qs.filter(status=status_filter)
    if facility_filter:
        bookings_qs = bookings_qs.filter(facility_id=facility_filter)
    if search_query:
        bookings_qs = bookings_qs.filter(
            models.Q(booking_id__icontains=search_query) |
            models.Q(member__name__icontains=search_query) |
            models.Q(member__membership_id__icontains=search_query) |
            models.Q(purpose__icontains=search_query)
        )

    all_bookings = HallBooking.objects.all()
    counts = {
        'total': all_bookings.count(),
        'confirmed': all_bookings.filter(status=BookingStatus.CONFIRMED).count(),
        'requested': all_bookings.filter(status=BookingStatus.REQUESTED).count(),
        'completed': all_bookings.filter(status=BookingStatus.COMPLETED).count(),
        'cancelled': all_bookings.filter(status=BookingStatus.CANCELLED).count(),
    }

    paginator = Paginator(bookings_qs, 15)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    can_manage = False
    profile = getattr(request.user, 'profile', None)
    if profile and profile.can_manage_events:
        can_manage = True

    facilities = Facility.objects.filter(is_active=True)

    context = {
        'page_obj': page_obj,
        'counts': counts,
        'status_filter': status_filter,
        'facility_filter': facility_filter,
        'search_query': search_query,
        'status_choices': BookingStatus.choices,
        'facilities': facilities,
        'can_manage': can_manage,
    }
    return render(request, 'bookings/booking_list.html', context)


@event_management_required
def booking_create(request):
    """
    Staff action to record a wedding / hall reservation for an institute member.
    Includes live availability check against double-booking.
    """
    search_query = request.GET.get('q', '').strip()
    members_found = []
    if search_query:
        members_found = Member.objects.active_records().search_query(search_query)[:15]

    if request.method == 'POST':
        form = StaffHallBookingForm(request.POST)
        if form.is_valid():
            member_id = form.cleaned_data['member_id']
            member = get_object_or_404(Member, pk=member_id, is_removed=False)
            facility = form.cleaned_data['facility']
            booking_date = form.cleaned_data['booking_date']
            slot = form.cleaned_data['slot']

            try:
                booking = create_hall_booking(
                    facility=facility,
                    member=member,
                    booking_date=booking_date,
                    slot=slot,
                    event_type=form.cleaned_data['event_type'],
                    purpose=form.cleaned_data['purpose'],
                    special_requests=form.cleaned_data['special_requests'],
                    advance_paid=form.cleaned_data['advance_paid'],
                    is_staff_confirmed=True,
                    approved_by=request.user
                )
                messages.success(
                    request,
                    f"Booking {booking.booking_id} confirmed for {member.name} at {facility.name} on {booking_date:%d-%m-%Y}."
                )
                return redirect('bookings:booking_detail', booking_id=booking.id)
            except ValidationError as e:
                messages.error(request, e.message if hasattr(e, 'message') else str(e))
    else:
        form = StaffHallBookingForm()

    context = {
        'form': form,
        'search_query': search_query,
        'members_found': members_found,
    }
    return render(request, 'bookings/booking_form.html', context)


@admin_login_required
def booking_detail(request, booking_id):
    """
    Comprehensive booking breakdown displaying facility, schedule,
    financial receipts, security deposit refund, and audit history.
    """
    booking = get_object_or_404(
        HallBooking.objects.select_related('facility', 'member', 'approved_by'),
        pk=booking_id
    )

    can_manage = False
    profile = getattr(request.user, 'profile', None)
    if profile and profile.can_manage_events:
        can_manage = True

    refund_form = DepositRefundForm(initial={'refund_amount': booking.deposit_amount})

    context = {
        'booking': booking,
        'can_manage': can_manage,
        'refund_form': refund_form,
    }
    return render(request, 'bookings/booking_detail.html', context)


@event_management_required
@require_POST
def booking_approve(request, booking_id):
    """Staff action to approve a requested hall booking."""
    booking = get_object_or_404(HallBooking, pk=booking_id)
    try:
        approve_hall_booking(booking, user=request.user)
        messages.success(request, f"Booking {booking.booking_id} has been approved.")
    except ValidationError as e:
        messages.error(request, str(e))
    return redirect('bookings:booking_detail', booking_id=booking.id)


@event_management_required
@require_POST
def booking_cancel(request, booking_id):
    """Staff action to cancel an active hall booking."""
    booking = get_object_or_404(HallBooking, pk=booking_id)
    reason = request.POST.get('cancellation_reason', '').strip()
    cancel_hall_booking(booking, reason=reason, user=request.user)
    messages.warning(request, f"Booking {booking.booking_id} has been cancelled.")
    return redirect('bookings:booking_detail', booking_id=booking.id)


@event_management_required
@require_POST
def booking_refund_deposit(request, booking_id):
    """Staff action to process the security deposit refund."""
    booking = get_object_or_404(HallBooking, pk=booking_id)
    form = DepositRefundForm(request.POST)
    if form.is_valid():
        refund_amount = form.cleaned_data['refund_amount']
        try:
            refund_security_deposit(booking, refund_amount=refund_amount, user=request.user)
            messages.success(request, f"Security deposit refund of ₹{refund_amount:,.2f} recorded.")
        except ValidationError as e:
            messages.error(request, str(e))
    else:
        messages.error(request, "Invalid refund amount.")

    return redirect('bookings:booking_detail', booking_id=booking.id)


@admin_login_required
def facility_list(request):
    """Staff directory of all halls, banquet lawns, and meeting rooms."""
    facilities = Facility.objects.all().order_by('name')

    can_manage = False
    profile = getattr(request.user, 'profile', None)
    if profile and profile.can_manage_events:
        can_manage = True

    context = {
        'facilities': facilities,
        'can_manage': can_manage,
    }
    return render(request, 'bookings/facility_list.html', context)


@event_management_required
def facility_create(request):
    """Staff action to add a new hall or facility."""
    if request.method == 'POST':
        form = FacilityForm(request.POST)
        if form.is_valid():
            fac = form.save()
            messages.success(request, f"Facility '{fac.name}' added successfully.")
            return redirect('bookings:facility_list')
    else:
        form = FacilityForm()

    context = {
        'form': form,
        'is_edit': False,
    }
    return render(request, 'bookings/facility_form.html', context)


@event_management_required
def facility_edit(request, facility_id):
    """Staff action to update an existing facility."""
    facility = get_object_or_404(Facility, pk=facility_id)

    if request.method == 'POST':
        form = FacilityForm(request.POST, instance=facility)
        if form.is_valid():
            form.save()
            messages.success(request, f"Facility '{facility.name}' updated successfully.")
            return redirect('bookings:facility_list')
    else:
        form = FacilityForm(instance=facility)

    context = {
        'form': form,
        'facility': facility,
        'is_edit': True,
    }
    return render(request, 'bookings/facility_form.html', context)


# =========================================================================
# MEMBER SELF-SERVICE PORTAL HALL BOOKING VIEWS
# =========================================================================

@member_login_required
def portal_booking_list(request):
    """
    Member Portal page showcasing all current and past hall bookings
    for the logged-in railway employee, plus a booking request form.
    """
    member_id = request.session['member_id']
    member = get_object_or_404(Member, pk=member_id, is_removed=False)

    bookings = HallBooking.objects.filter(member=member).select_related('facility').order_by('-booking_date', '-booked_at')
    facilities = Facility.objects.filter(is_active=True).order_by('name')
    form = MemberPortalBookingForm()

    context = {
        'member': member,
        'bookings': bookings,
        'facilities': facilities,
        'form': form,
    }
    return render(request, 'portal/hall_bookings.html', context)


@member_login_required
@require_POST
def portal_booking_request(request):
    """Member submits a hall reservation request from portal."""
    member_id = request.session['member_id']
    member = get_object_or_404(Member, pk=member_id, is_removed=False)

    form = MemberPortalBookingForm(request.POST)
    if form.is_valid():
        facility = form.cleaned_data['facility']
        booking_date = form.cleaned_data['booking_date']
        slot = form.cleaned_data['slot']

        try:
            booking = create_hall_booking(
                facility=facility,
                member=member,
                booking_date=booking_date,
                slot=slot,
                event_type=form.cleaned_data['event_type'],
                purpose=form.cleaned_data['purpose'],
                special_requests=form.cleaned_data['special_requests'],
                advance_paid=Decimal('0.00'),
                is_staff_confirmed=False,
                approved_by=None
            )
            messages.success(
                request,
                f"Your reservation request ({booking.booking_id}) for {facility.name} on "
                f"{booking_date:%d-%m-%Y} has been submitted to the Institute Office for review!"
            )
        except ValidationError as e:
            messages.error(request, e.message if hasattr(e, 'message') else str(e))
    else:
        messages.error(request, "Please correct the errors in the booking form.")

    return redirect('bookings:portal_bookings')


@member_login_required
@require_POST
def portal_booking_cancel(request, booking_id):
    """Member cancels their pending booking request from portal."""
    member_id = request.session['member_id']
    member = get_object_or_404(Member, pk=member_id, is_removed=False)
    booking = get_object_or_404(HallBooking, pk=booking_id, member=member)

    if booking.status in [BookingStatus.COMPLETED, BookingStatus.CANCELLED]:
        messages.error(request, "Cannot cancel this booking.")
        return redirect('bookings:portal_bookings')

    cancel_hall_booking(booking, reason="Member cancelled via portal")
    messages.info(request, f"Your reservation request ({booking.booking_id}) has been cancelled.")
    return redirect('bookings:portal_bookings')
