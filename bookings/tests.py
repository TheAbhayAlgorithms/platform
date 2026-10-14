from datetime import date, timedelta
from decimal import Decimal
import pytest

from django.test import Client
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from accounts.models import UserProfile, RoleChoices
from members.models import Member, MemberStatus, DepartmentChoices
from notifications.models import WhatsAppMessageLog
from bookings.models import (
    Facility,
    FacilityType,
    HallBooking,
    BookingSlot,
    BookingStatus,
    PaymentStatus,
    EventType,
)
from bookings.forms import FacilityForm, StaffHallBookingForm, MemberPortalBookingForm, DepositRefundForm
from bookings.services import (
    check_facility_availability,
    create_hall_booking,
    approve_hall_booking,
    cancel_hall_booking,
    refund_security_deposit,
)


@pytest.fixture
def active_member(db):
    return Member.objects.create(
        name="Vikram Sharma",
        phone="+919876543210",
        employee_id="PF-1001",
        department=DepartmentChoices.OPERATING,
        status=MemberStatus.ACTIVE,
        whatsapp_opt_in=True
    )


@pytest.fixture
def suspended_member(db):
    return Member.objects.create(
        name="Ramesh Yadav",
        phone="+919876543211",
        employee_id="PF-1002",
        department=DepartmentChoices.MECHANICAL,
        status=MemberStatus.SUSPENDED,
        whatsapp_opt_in=True
    )


@pytest.fixture
def facility_hall(db):
    return Facility.objects.create(
        name="Grand Banquet Hall",
        facility_type=FacilityType.BANQUET_HALL,
        capacity=300,
        rent_per_slot=Decimal('6000.00'),
        full_day_rent=Decimal('10000.00'),
        security_deposit=Decimal('3000.00'),
        flat_electricity_charge=Decimal('1500.00'),
        description="Air conditioned grand banquet hall with stage.",
        is_active=True
    )


@pytest.fixture
def facility_lawn(db):
    return Facility.objects.create(
        name="Open Wedding Lawns",
        facility_type=FacilityType.WEDDING_LAWN,
        capacity=600,
        rent_per_slot=Decimal('8000.00'),
        full_day_rent=Decimal('14000.00'),
        security_deposit=Decimal('5000.00'),
        flat_electricity_charge=Decimal('2000.00'),
        description="Lush green open party lawns.",
        is_active=True
    )


@pytest.fixture
def admin_user(db):
    user = User.objects.create_user(username="admin_user", password="password123")
    UserProfile.objects.create(user=user, role=RoleChoices.SUPER_ADMIN)
    return user


@pytest.fixture
def event_manager_user(db):
    user = User.objects.create_user(username="event_mgr", password="password123")
    UserProfile.objects.create(user=user, role=RoleChoices.EVENT_MANAGER)
    return user


@pytest.fixture
def viewer_user(db):
    user = User.objects.create_user(username="viewer_user", password="password123")
    UserProfile.objects.create(user=user, role=RoleChoices.VIEWER)
    return user


# =========================================================================
# 1. MODEL & ID GENERATION TESTS
# =========================================================================

@pytest.mark.django_db
def test_facility_creation_and_str(facility_hall):
    assert facility_hall.name == "Grand Banquet Hall"
    assert "Grand Banquet Hall" in str(facility_hall)
    assert facility_hall.capacity == 300


@pytest.mark.django_db
def test_sequential_booking_id_generation(facility_hall, active_member):
    target_date = timezone.now().date() + timedelta(days=20)
    b1 = HallBooking.objects.create(
        facility=facility_hall,
        member=active_member,
        booking_date=target_date,
        slot=BookingSlot.MORNING,
        purpose="Family Function 1",
        rent_amount=Decimal('6000.00'),
        deposit_amount=Decimal('3000.00'),
        electricity_charges=Decimal('1500.00'),
        total_amount=Decimal('10500.00'),
    )
    b2 = HallBooking.objects.create(
        facility=facility_hall,
        member=active_member,
        booking_date=target_date + timedelta(days=1),
        slot=BookingSlot.EVENING,
        purpose="Family Function 2",
        rent_amount=Decimal('6000.00'),
        deposit_amount=Decimal('3000.00'),
        electricity_charges=Decimal('1500.00'),
        total_amount=Decimal('10500.00'),
    )

    year = target_date.year
    assert b1.booking_id == f"HB-{year}-00001"
    assert b2.booking_id == f"HB-{year}-00002"
    assert b1.balance_amount == Decimal('10500.00')
    assert b1.balance_due == Decimal('10500.00')


# =========================================================================
# 2. AVAILABILITY & OVERLAP LOGIC TESTS
# =========================================================================

@pytest.mark.django_db
def test_slot_availability_empty_date(facility_hall):
    target_date = timezone.now().date() + timedelta(days=10)
    assert check_facility_availability(facility_hall, target_date, BookingSlot.MORNING) is True
    assert check_facility_availability(facility_hall, target_date, BookingSlot.EVENING) is True
    assert check_facility_availability(facility_hall, target_date, BookingSlot.FULL_DAY) is True


@pytest.mark.django_db
def test_slot_overlap_with_morning_booking(facility_hall, active_member):
    target_date = timezone.now().date() + timedelta(days=15)
    HallBooking.objects.create(
        facility=facility_hall,
        member=active_member,
        booking_date=target_date,
        slot=BookingSlot.MORNING,
        status=BookingStatus.CONFIRMED,
        rent_amount=Decimal('6000.00'),
        deposit_amount=Decimal('3000.00'),
        electricity_charges=Decimal('1500.00'),
        total_amount=Decimal('10500.00'),
    )

    # Conflicting requests: MORNING and FULL_DAY
    assert check_facility_availability(facility_hall, target_date, BookingSlot.MORNING) is False
    assert check_facility_availability(facility_hall, target_date, BookingSlot.FULL_DAY) is False
    # Non-conflicting request: EVENING is free!
    assert check_facility_availability(facility_hall, target_date, BookingSlot.EVENING) is True


@pytest.mark.django_db
def test_slot_overlap_with_evening_booking(facility_hall, active_member):
    target_date = timezone.now().date() + timedelta(days=16)
    HallBooking.objects.create(
        facility=facility_hall,
        member=active_member,
        booking_date=target_date,
        slot=BookingSlot.EVENING,
        status=BookingStatus.CONFIRMED,
        rent_amount=Decimal('6000.00'),
        deposit_amount=Decimal('3000.00'),
        electricity_charges=Decimal('1500.00'),
        total_amount=Decimal('10500.00'),
    )

    # Conflicting requests: EVENING and FULL_DAY
    assert check_facility_availability(facility_hall, target_date, BookingSlot.EVENING) is False
    assert check_facility_availability(facility_hall, target_date, BookingSlot.FULL_DAY) is False
    # Non-conflicting: MORNING is free!
    assert check_facility_availability(facility_hall, target_date, BookingSlot.MORNING) is True


@pytest.mark.django_db
def test_slot_overlap_with_full_day_booking(facility_hall, active_member):
    target_date = timezone.now().date() + timedelta(days=17)
    HallBooking.objects.create(
        facility=facility_hall,
        member=active_member,
        booking_date=target_date,
        slot=BookingSlot.FULL_DAY,
        status=BookingStatus.CONFIRMED,
        rent_amount=Decimal('10000.00'),
        deposit_amount=Decimal('3000.00'),
        electricity_charges=Decimal('1500.00'),
        total_amount=Decimal('14500.00'),
    )

    # All slots blocked for this facility on target_date
    assert check_facility_availability(facility_hall, target_date, BookingSlot.MORNING) is False
    assert check_facility_availability(facility_hall, target_date, BookingSlot.EVENING) is False
    assert check_facility_availability(facility_hall, target_date, BookingSlot.FULL_DAY) is False


@pytest.mark.django_db
def test_cancelled_booking_frees_slot(facility_hall, active_member):
    target_date = timezone.now().date() + timedelta(days=18)
    b = HallBooking.objects.create(
        facility=facility_hall,
        member=active_member,
        booking_date=target_date,
        slot=BookingSlot.FULL_DAY,
        status=BookingStatus.CANCELLED,
        rent_amount=Decimal('10000.00'),
        deposit_amount=Decimal('3000.00'),
        electricity_charges=Decimal('1500.00'),
        total_amount=Decimal('14500.00'),
    )

    assert check_facility_availability(facility_hall, target_date, BookingSlot.FULL_DAY) is True


@pytest.mark.django_db
def test_different_facilities_do_not_conflict(facility_hall, facility_lawn, active_member):
    target_date = timezone.now().date() + timedelta(days=19)
    HallBooking.objects.create(
        facility=facility_hall,
        member=active_member,
        booking_date=target_date,
        slot=BookingSlot.FULL_DAY,
        status=BookingStatus.CONFIRMED,
        rent_amount=Decimal('10000.00'),
        deposit_amount=Decimal('3000.00'),
        electricity_charges=Decimal('1500.00'),
        total_amount=Decimal('14500.00'),
    )

    # Lawn is free on the same date!
    assert check_facility_availability(facility_lawn, target_date, BookingSlot.FULL_DAY) is True


# =========================================================================
# 3. BOOKING CREATION & SERVICE TESTS
# =========================================================================

@pytest.mark.django_db
def test_create_hall_booking_success(facility_hall, active_member, admin_user):
    target_date = timezone.now().date() + timedelta(days=25)
    booking = create_hall_booking(
        facility=facility_hall,
        member=active_member,
        booking_date=target_date,
        slot=BookingSlot.EVENING,
        event_type=EventType.WEDDING,
        purpose="Daughter Wedding",
        special_requests="Need extra sound speakers",
        advance_paid=Decimal('5000.00'),
        is_staff_confirmed=True,
        approved_by=admin_user
    )

    assert booking.status == BookingStatus.CONFIRMED
    assert booking.rent_amount == Decimal('6000.00')
    assert booking.deposit_amount == Decimal('3000.00')
    assert booking.electricity_charges == Decimal('1500.00')
    assert booking.total_amount == Decimal('10500.00')
    assert booking.advance_paid == Decimal('5000.00')
    assert booking.balance_amount == Decimal('5500.00')
    assert booking.payment_status == PaymentStatus.ADVANCE_PAID
    assert booking.approved_by == admin_user

    # WhatsApp message generated
    assert WhatsAppMessageLog.objects.filter(member=active_member).exists()


@pytest.mark.django_db
def test_create_hall_booking_full_day_pricing(facility_hall, active_member):
    target_date = timezone.now().date() + timedelta(days=26)
    booking = create_hall_booking(
        facility=facility_hall,
        member=active_member,
        booking_date=target_date,
        slot=BookingSlot.FULL_DAY,
        event_type=EventType.RECEPTION,
        purpose="Grand Reception",
        advance_paid=Decimal('14500.00'),
        is_staff_confirmed=False
    )

    assert booking.status == BookingStatus.REQUESTED
    assert booking.rent_amount == Decimal('10000.00')
    assert booking.total_amount == Decimal('14500.00')
    assert booking.payment_status == PaymentStatus.FULLY_PAID
    assert booking.balance_amount == Decimal('0.00')


@pytest.mark.django_db
def test_create_hall_booking_past_date_rejected(facility_hall, active_member):
    past_date = timezone.now().date() - timedelta(days=1)
    with pytest.raises(ValidationError, match="past dates"):
        create_hall_booking(
            facility=facility_hall,
            member=active_member,
            booking_date=past_date,
            slot=BookingSlot.MORNING,
            event_type=EventType.OTHER,
            purpose="Past Event"
        )


@pytest.mark.django_db
def test_create_hall_booking_suspended_member_rejected(facility_hall, suspended_member):
    target_date = timezone.now().date() + timedelta(days=30)
    with pytest.raises(ValidationError, match="suspended"):
        create_hall_booking(
            facility=facility_hall,
            member=suspended_member,
            booking_date=target_date,
            slot=BookingSlot.MORNING,
            event_type=EventType.OTHER,
            purpose="Suspended Member Event"
        )


@pytest.mark.django_db
def test_create_hall_booking_double_booking_rejected(facility_hall, active_member):
    target_date = timezone.now().date() + timedelta(days=35)
    create_hall_booking(
        facility=facility_hall,
        member=active_member,
        booking_date=target_date,
        slot=BookingSlot.MORNING,
        event_type=EventType.ENGAGEMENT,
        purpose="Engagement 1"
    )

    with pytest.raises(ValidationError, match="already reserved"):
        create_hall_booking(
            facility=facility_hall,
            member=active_member,
            booking_date=target_date,
            slot=BookingSlot.MORNING,
            event_type=EventType.ENGAGEMENT,
            purpose="Engagement 2 Conflict"
        )


@pytest.mark.django_db
def test_create_hall_booking_excess_advance_rejected(facility_hall, active_member):
    target_date = timezone.now().date() + timedelta(days=40)
    with pytest.raises(ValidationError, match="cannot exceed grand total"):
        create_hall_booking(
            facility=facility_hall,
            member=active_member,
            booking_date=target_date,
            slot=BookingSlot.MORNING,
            event_type=EventType.ENGAGEMENT,
            purpose="Engagement",
            advance_paid=Decimal('50000.00')
        )


# =========================================================================
# 4. APPROVAL, CANCELLATION & DEPOSIT REFUND
# =========================================================================

@pytest.mark.django_db
def test_approve_hall_booking(facility_hall, active_member, admin_user):
    target_date = timezone.now().date() + timedelta(days=45)
    booking = create_hall_booking(
        facility=facility_hall,
        member=active_member,
        booking_date=target_date,
        slot=BookingSlot.EVENING,
        event_type=EventType.BIRTHDAY,
        purpose="Birthday Party",
        is_staff_confirmed=False
    )
    assert booking.status == BookingStatus.REQUESTED

    approved = approve_hall_booking(booking, user=admin_user)
    assert approved.status == BookingStatus.CONFIRMED
    assert approved.approved_by == admin_user


@pytest.mark.django_db
def test_cancel_hall_booking(facility_hall, active_member, admin_user):
    target_date = timezone.now().date() + timedelta(days=50)
    booking = create_hall_booking(
        facility=facility_hall,
        member=active_member,
        booking_date=target_date,
        slot=BookingSlot.FULL_DAY,
        event_type=EventType.WEDDING,
        purpose="Wedding Ceremony"
    )

    cancelled = cancel_hall_booking(booking, reason="Member postponed function", user=admin_user)
    assert cancelled.status == BookingStatus.CANCELLED
    assert cancelled.cancellation_reason == "Member postponed function"


@pytest.mark.django_db
def test_refund_security_deposit_validations(facility_hall, active_member, admin_user):
    target_date = timezone.now().date() + timedelta(days=55)
    booking = create_hall_booking(
        facility=facility_hall,
        member=active_member,
        booking_date=target_date,
        slot=BookingSlot.EVENING,
        event_type=EventType.WEDDING,
        purpose="Wedding"
    )

    # Excessive refund validation
    with pytest.raises(ValidationError, match="Refund amount must be between"):
        refund_security_deposit(booking, refund_amount=Decimal('4000.00'))

    # Successful refund
    refunded = refund_security_deposit(booking, refund_amount=Decimal('3000.00'), user=admin_user)
    assert refunded.deposit_refunded is True
    assert refunded.deposit_refund_amount == Decimal('3000.00')
    assert refunded.deposit_refund_date == timezone.now().date()
    assert refunded.status == BookingStatus.COMPLETED


# =========================================================================
# 5. STAFF VIEWS & RBAC PERMISSION TESTS
# =========================================================================

@pytest.mark.django_db
def test_staff_booking_list_access(facility_hall, active_member, event_manager_user, viewer_user):
    client = Client()
    target_url = reverse('bookings:booking_list')

    # Unauthenticated redirect
    resp = client.get(target_url)
    assert resp.status_code == 302

    # Event Manager can view
    client.force_login(event_manager_user)
    resp = client.get(target_url)
    assert resp.status_code == 200
    assert "Wedding &amp; Hall Bookings" in resp.content.decode()

    # Viewer can view
    client.force_login(viewer_user)
    resp = client.get(target_url)
    assert resp.status_code == 200


@pytest.mark.django_db
def test_staff_booking_create_view_rbac(facility_hall, active_member, event_manager_user, viewer_user):
    client = Client()
    create_url = reverse('bookings:booking_create')

    # Viewer forbidden
    client.force_login(viewer_user)
    resp = client.get(create_url)
    assert resp.status_code == 403

    # Event manager allowed
    client.force_login(event_manager_user)
    resp = client.get(create_url)
    assert resp.status_code == 200

    # Successful POST
    target_date = (timezone.now().date() + timedelta(days=60)).strftime('%Y-%m-%d')
    post_data = {
        'member_id': active_member.id,
        'facility': facility_hall.id,
        'booking_date': target_date,
        'slot': BookingSlot.MORNING,
        'event_type': EventType.WEDDING,
        'purpose': "Office Staff Marriage",
        'advance_paid': '2000.00',
        'special_requests': 'Stage lighting'
    }
    resp = client.post(create_url, post_data)
    assert resp.status_code == 302
    assert HallBooking.objects.filter(purpose="Office Staff Marriage").exists()


@pytest.mark.django_db
def test_staff_facility_create_and_edit_rbac(facility_hall, event_manager_user, viewer_user):
    client = Client()
    create_fac_url = reverse('bookings:facility_create')
    edit_fac_url = reverse('bookings:facility_edit', kwargs={'facility_id': facility_hall.id})

    # Viewer forbidden
    client.force_login(viewer_user)
    assert client.get(create_fac_url).status_code == 403
    assert client.get(edit_fac_url).status_code == 403

    # Event manager allowed
    client.force_login(event_manager_user)
    resp = client.get(create_fac_url)
    assert resp.status_code == 200

    # Create new facility POST
    post_data = {
        'name': 'Conference Boardroom A',
        'facility_type': FacilityType.CONFERENCE_ROOM,
        'capacity': 50,
        'rent_per_slot': '2000.00',
        'full_day_rent': '3500.00',
        'security_deposit': '1000.00',
        'flat_electricity_charge': '500.00',
        'description': 'Projector and mic setup',
        'is_active': True
    }
    resp = client.post(create_fac_url, post_data)
    assert resp.status_code == 302
    assert Facility.objects.filter(name='Conference Boardroom A').exists()


@pytest.mark.django_db
def test_staff_booking_approval_and_cancel_actions(facility_hall, active_member, event_manager_user):
    target_date = timezone.now().date() + timedelta(days=65)
    booking = create_hall_booking(
        facility=facility_hall,
        member=active_member,
        booking_date=target_date,
        slot=BookingSlot.EVENING,
        event_type=EventType.BIRTHDAY,
        purpose="Birthday Celebrations",
        is_staff_confirmed=False
    )

    client = Client()
    client.force_login(event_manager_user)

    # Approve
    approve_url = reverse('bookings:booking_approve', kwargs={'booking_id': booking.id})
    resp = client.post(approve_url)
    assert resp.status_code == 302
    booking.refresh_from_db()
    assert booking.status == BookingStatus.CONFIRMED

    # Cancel
    cancel_url = reverse('bookings:booking_cancel', kwargs={'booking_id': booking.id})
    resp = client.post(cancel_url, {'cancellation_reason': 'Staff requested cancel'})
    assert resp.status_code == 302
    booking.refresh_from_db()
    assert booking.status == BookingStatus.CANCELLED
    assert booking.cancellation_reason == 'Staff requested cancel'


# =========================================================================
# 6. MEMBER SELF-SERVICE PORTAL TESTS
# =========================================================================

@pytest.mark.django_db
def test_portal_booking_list_view(client, active_member, facility_hall):
    portal_url = reverse('bookings:portal_bookings')

    # Unauthenticated redirect to member login
    resp = client.get(portal_url)
    assert resp.status_code == 302
    assert resp.url == reverse('portal:login')

    # Authenticate member session
    session = client.session
    session['member_id'] = active_member.id
    session['member_authenticated'] = True
    session.save()

    resp = client.get(portal_url)
    assert resp.status_code == 200
    assert "Institute Hall &amp; Lawn Reservations" in resp.content.decode()
    assert facility_hall.name in resp.content.decode()


@pytest.mark.django_db
def test_portal_booking_request_submission(client, active_member, facility_hall):
    session = client.session
    session['member_id'] = active_member.id
    session['member_authenticated'] = True
    session.save()

    request_url = reverse('bookings:portal_request')
    target_date = (timezone.now().date() + timedelta(days=70)).strftime('%Y-%m-%d')
    post_data = {
        'facility': facility_hall.id,
        'booking_date': target_date,
        'slot': BookingSlot.EVENING,
        'event_type': EventType.RETIREMENT,
        'purpose': 'Retirement dinner party',
        'special_requests': 'Require 100 extra chairs'
    }

    resp = client.post(request_url, post_data)
    assert resp.status_code == 302

    booking = HallBooking.objects.get(purpose='Retirement dinner party')
    assert booking.member == active_member
    assert booking.status == BookingStatus.REQUESTED
    assert booking.advance_paid == Decimal('0.00')


@pytest.mark.django_db
def test_portal_booking_cancel(client, active_member, facility_hall):
    target_date = timezone.now().date() + timedelta(days=75)
    booking = create_hall_booking(
        facility=facility_hall,
        member=active_member,
        booking_date=target_date,
        slot=BookingSlot.MORNING,
        event_type=EventType.OTHER,
        purpose='Member Cancel Test',
        is_staff_confirmed=False
    )

    session = client.session
    session['member_id'] = active_member.id
    session['member_authenticated'] = True
    session.save()

    cancel_url = reverse('bookings:portal_cancel', kwargs={'booking_id': booking.id})
    resp = client.post(cancel_url)
    assert resp.status_code == 302

    booking.refresh_from_db()
    assert booking.status == BookingStatus.CANCELLED
    assert "portal" in booking.cancellation_reason.lower()
