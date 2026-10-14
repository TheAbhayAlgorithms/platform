import io
import csv
from datetime import timedelta
from decimal import Decimal
import pytest
import openpyxl
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from accounts.models import UserProfile, RoleChoices
from members.models import Member, MemberStatus, DepartmentChoices
from notifications.models import WhatsAppMessageLog
from events.models import (
    Event,
    EventRegistration,
    EventCategory,
    EventStatus,
    RegistrationStatus,
    EventPaymentStatus,
)
from events.services import (
    register_member_for_event,
    cancel_event_registration,
    toggle_event_check_in,
    get_event_headcount_stats,
    export_event_attendees_excel,
    export_event_attendees_csv,
)


@pytest.fixture
def superadmin_user(db):
    user = User.objects.create_user(username='evt_admin', password='AdminPassword@2026!')
    UserProfile.objects.create(user=user, role=RoleChoices.SUPER_ADMIN, phone='+919876543300')
    return user


@pytest.fixture
def event_manager_user(db):
    user = User.objects.create_user(username='evt_mgr', password='MgrPassword@2026!')
    UserProfile.objects.create(user=user, role=RoleChoices.EVENT_MANAGER, phone='+919876543301')
    return user


@pytest.fixture
def viewer_user(db):
    user = User.objects.create_user(username='evt_view', password='ViewPassword@2026!')
    UserProfile.objects.create(user=user, role=RoleChoices.VIEWER, phone='+919876543302')
    return user


@pytest.fixture
def active_member(db):
    return Member.objects.create(
        name="Vikram Sethi",
        phone="+919876511111",
        employee_id="PF-2001",
        department=DepartmentChoices.OPERATING,
        status=MemberStatus.ACTIVE,
        whatsapp_opt_in=True
    )


@pytest.fixture
def second_member(db):
    return Member.objects.create(
        name="Deepa Sharma",
        phone="+919876522222",
        employee_id="PF-2002",
        department=DepartmentChoices.COMMERCIAL,
        status=MemberStatus.ACTIVE,
        whatsapp_opt_in=False
    )


@pytest.fixture
def upcoming_festival(db):
    now = timezone.now()
    return Event.objects.create(
        title="Diwali Milan 2026",
        category=EventCategory.FESTIVAL,
        description="Annual Diwali festival celebration with cultural evening and dinner.",
        venue="Institute Main Auditorium & Lawns",
        start_date_time=now + timedelta(days=10),
        end_date_time=now + timedelta(days=10, hours=5),
        registration_deadline=now + timedelta(days=9),
        capacity=50,
        member_entry_fee=Decimal('0.00'),
        guest_entry_fee=Decimal('150.00'),
        max_guests_per_member=4,
        status=EventStatus.PUBLISHED,
        is_active=True
    )


@pytest.mark.django_db
class TestEventModelAndValidation:
    """Tests model constraints, date-time validation, and capacity calculations."""

    def test_event_end_date_before_start_date_raises_validation_error(self):
        now = timezone.now()
        event = Event(
            title="Invalid Event",
            start_date_time=now + timedelta(days=5),
            end_date_time=now + timedelta(days=4),  # invalid: before start
            venue="Hall A"
        )
        with pytest.raises(ValidationError):
            event.clean()

    def test_event_registration_deadline_after_start_date_raises_validation_error(self):
        now = timezone.now()
        event = Event(
            title="Invalid Deadline Event",
            start_date_time=now + timedelta(days=5),
            end_date_time=now + timedelta(days=6),
            registration_deadline=now + timedelta(days=7),  # invalid: after start
            venue="Hall A"
        )
        with pytest.raises(ValidationError):
            event.clean()

    def test_event_capacity_and_headcount_properties(self, upcoming_festival, active_member, second_member):
        assert upcoming_festival.capacity == 50
        assert upcoming_festival.registered_headcount == 0
        assert upcoming_festival.remaining_capacity == 50
        assert upcoming_festival.is_full is False
        assert upcoming_festival.is_registration_open is True

        # Register member 1: 1 member + 2 family + 1 guest = 4 attendees
        register_member_for_event(
            event=upcoming_festival,
            member=active_member,
            num_family_members=2,
            num_guests=1
        )
        upcoming_festival.refresh_from_db()
        assert upcoming_festival.registered_headcount == 4
        assert upcoming_festival.remaining_capacity == 46


@pytest.mark.django_db
class TestEventRegistrationServices:
    """Tests business logic for event RSVP, capacity limits, fee calculation, and check-in."""

    def test_successful_event_registration_and_whatsapp_confirmation(self, upcoming_festival, active_member):
        initial_logs_count = WhatsAppMessageLog.objects.count()

        reg = register_member_for_event(
            event=upcoming_festival,
            member=active_member,
            num_family_members=2,
            num_guests=2,
            notes="Requires vegetarian seating"
        )

        assert reg.event == upcoming_festival
        assert reg.member == active_member
        assert reg.num_family_members == 2
        assert reg.num_guests == 2
        assert reg.total_headcount == 5  # 1 member + 2 family + 2 guests
        # Fee: 0 member + 2 * 150 = 300.00
        assert reg.calculated_fee == Decimal('300.00')
        assert reg.payment_status == EventPaymentStatus.PENDING
        assert reg.status == RegistrationStatus.CONFIRMED
        assert reg.checked_in is False

        # WhatsApp alert was dispatched because active_member has whatsapp_opt_in=True
        assert WhatsAppMessageLog.objects.count() == initial_logs_count + 1
        log = WhatsAppMessageLog.objects.latest('created_at')
        assert "Diwali Milan 2026" in log.message_body
        assert active_member.membership_id in log.message_body

    def test_registration_with_dpdp_opt_out_skips_whatsapp(self, upcoming_festival, second_member):
        initial_logs_count = WhatsAppMessageLog.objects.count()

        reg = register_member_for_event(
            event=upcoming_festival,
            member=second_member,
            num_family_members=1,
            num_guests=0
        )
        assert reg.status == RegistrationStatus.CONFIRMED
        # No WhatsApp message dispatched
        assert WhatsAppMessageLog.objects.count() == initial_logs_count

    def test_prevent_duplicate_event_registration(self, upcoming_festival, active_member):
        register_member_for_event(event=upcoming_festival, member=active_member)

        # Second attempt must be rejected
        with pytest.raises(ValidationError) as exc:
            register_member_for_event(event=upcoming_festival, member=active_member)
        assert "already registered" in str(exc.value)

    def test_guest_limit_enforced(self, upcoming_festival, active_member):
        # max_guests_per_member is 4
        with pytest.raises(ValidationError) as exc:
            register_member_for_event(event=upcoming_festival, member=active_member, num_guests=5)
        assert "at most 4" in str(exc.value)

    def test_capacity_overflow_rejected(self, active_member, second_member):
        now = timezone.now()
        small_event = Event.objects.create(
            title="Exclusive Dinner",
            start_date_time=now + timedelta(days=5),
            end_date_time=now + timedelta(days=5, hours=3),
            capacity=3,  # only 3 seats
            status=EventStatus.PUBLISHED,
            is_active=True
        )

        # Register 1 member + 1 family = 2 attendees (1 seat left)
        register_member_for_event(event=small_event, member=active_member, num_family_members=1)

        # Attempt to register 2 attendees -> exceeds capacity (requires 2, only 1 left)
        with pytest.raises(ValidationError) as exc:
            register_member_for_event(event=small_event, member=second_member, num_family_members=1)
        assert "capacity" in str(exc.value).lower()

    def test_suspended_or_removed_member_cannot_register(self, upcoming_festival, active_member):
        active_member.status = MemberStatus.SUSPENDED
        active_member.save()

        with pytest.raises(ValidationError) as exc:
            register_member_for_event(event=upcoming_festival, member=active_member)
        assert "suspended" in str(exc.value).lower()

    def test_cancel_registration_releases_capacity(self, upcoming_festival, active_member):
        reg = register_member_for_event(event=upcoming_festival, member=active_member, num_family_members=2)
        assert upcoming_festival.registered_headcount == 3

        cancel_event_registration(reg, reason="Unable to travel")
        upcoming_festival.refresh_from_db()
        assert upcoming_festival.registered_headcount == 0

    def test_check_in_toggle_service(self, upcoming_festival, active_member):
        reg = register_member_for_event(event=upcoming_festival, member=active_member)
        assert reg.checked_in is False
        assert reg.checked_in_at is None

        # Check In
        status = toggle_event_check_in(reg)
        assert status is True
        assert reg.checked_in is True
        assert reg.checked_in_at is not None

        # Undo Check In
        status_undo = toggle_event_check_in(reg)
        assert status_undo is False
        assert reg.checked_in is False
        assert reg.checked_in_at is None

    def test_get_event_headcount_stats(self, upcoming_festival, active_member, second_member):
        reg1 = register_member_for_event(upcoming_festival, active_member, num_family_members=2, num_guests=1)
        reg2 = register_member_for_event(upcoming_festival, second_member, num_family_members=0, num_guests=2)

        toggle_event_check_in(reg1)

        stats = get_event_headcount_stats(upcoming_festival)
        assert stats['total_registrations'] == 2
        assert stats['member_count'] == 2
        assert stats['family_count'] == 2
        assert stats['guest_count'] == 3
        assert stats['total_headcount'] == 7
        assert stats['checked_in_members'] == 1
        assert stats['total_checked_in'] == 4  # reg1 has 1 + 2 + 1 = 4
        assert stats['total_fees'] == Decimal('450.00')  # 3 guests * 150


class TestEventExports:
    """Tests attendee export generators for Excel and CSV formats."""

    def test_export_event_attendees_excel(self, upcoming_festival, active_member):
        register_member_for_event(upcoming_festival, active_member, num_family_members=1, num_guests=1)

        excel_bytes = export_event_attendees_excel(upcoming_festival)
        assert isinstance(excel_bytes, bytes)
        assert len(excel_bytes) > 0

        wb = openpyxl.load_workbook(io.BytesIO(excel_bytes))
        ws = wb.active
        assert "DIWALI MILAN 2026" in ws.cell(row=1, column=1).value


    def test_export_event_attendees_csv(self, upcoming_festival, active_member):
        register_member_for_event(upcoming_festival, active_member, num_family_members=1, num_guests=1)

        csv_str = export_event_attendees_csv(upcoming_festival)
        reader = list(csv.reader(io.StringIO(csv_str)))
        assert "Membership ID" in reader[0]
        assert active_member.membership_id in reader[1]
        assert active_member.name in reader[1]


@pytest.mark.django_db
class TestEventViewsAndPermissions:
    """Tests web endpoints, role permissions, and member portal RSVP interactions."""

    def _login_staff(self, client, user):
        client.force_login(user)
        session = client.session
        session['otp_verified'] = True
        session.save()

    def _login_portal_member(self, client, member):
        session = client.session
        session['member_authenticated'] = True
        session['member_id'] = member.id
        session.save()

    def test_unauthenticated_staff_redirected(self, client, upcoming_festival):
        urls = [
            reverse('events:event_list'),
            reverse('events:event_create'),
            reverse('events:event_detail', args=[upcoming_festival.id]),
        ]
        for url in urls:
            resp = client.get(url)
            assert resp.status_code == 302
            assert reverse('accounts:login') in resp.url

    def test_viewer_role_access_and_restrictions(self, client, viewer_user, upcoming_festival):
        self._login_staff(client, viewer_user)

        # Viewer can view list and detail
        resp_list = client.get(reverse('events:event_list'))
        assert resp_list.status_code == 200

        resp_detail = client.get(reverse('events:event_detail', args=[upcoming_festival.id]))
        assert resp_detail.status_code == 200

        # Viewer cannot create event (403 forbidden)
        resp_create = client.get(reverse('events:event_create'))
        assert resp_create.status_code == 403

        # Viewer cannot register a member
        resp_reg = client.get(reverse('events:event_register_member', args=[upcoming_festival.id]))
        assert resp_reg.status_code == 403

    def test_event_manager_can_create_and_manage_events(self, client, event_manager_user):
        self._login_staff(client, event_manager_user)
        now = timezone.now()

        # 1. Create event
        resp_create = client.post(reverse('events:event_create'), {
            'title': 'Republic Day Gala 2027',
            'category': EventCategory.NATIONAL_DAY,
            'venue': 'Auditorium',
            'start_date_time': (now + timedelta(days=30)).strftime('%Y-%m-%dT%H:%M'),
            'end_date_time': (now + timedelta(days=30, hours=4)).strftime('%Y-%m-%dT%H:%M'),
            'capacity': 100,
            'member_entry_fee': '0.00',
            'guest_entry_fee': '100.00',
            'max_guests_per_member': 2,
            'status': EventStatus.PUBLISHED,
            'is_active': True,
        })
        assert resp_create.status_code in [302, 303]
        event = Event.objects.get(title='Republic Day Gala 2027')
        assert event.created_by == event_manager_user

        # 2. Edit event
        resp_edit = client.post(reverse('events:event_edit', args=[event.id]), {
            'title': 'Republic Day Gala 2027 - Updated',
            'category': EventCategory.NATIONAL_DAY,
            'venue': 'Auditorium & Lawns',
            'start_date_time': event.start_date_time.strftime('%Y-%m-%dT%H:%M'),
            'end_date_time': event.end_date_time.strftime('%Y-%m-%dT%H:%M'),
            'capacity': 120,
            'member_entry_fee': '0.00',
            'guest_entry_fee': '100.00',
            'max_guests_per_member': 2,
            'status': EventStatus.PUBLISHED,
            'is_active': True,
        })
        assert resp_edit.status_code in [302, 303]
        event.refresh_from_db()
        assert event.title == 'Republic Day Gala 2027 - Updated'
        assert event.capacity == 120

    def test_staff_register_member_and_check_in_flow(self, client, event_manager_user, upcoming_festival, active_member):
        self._login_staff(client, event_manager_user)

        # 1. Staff registers member manually
        resp_reg = client.post(reverse('events:event_register_member', args=[upcoming_festival.id]), {
            'member_id': active_member.id,
            'num_family_members': 2,
            'num_guests': 1,
            'notes': 'Staff recorded registration'
        })
        assert resp_reg.status_code in [302, 303]

        reg = EventRegistration.objects.get(event=upcoming_festival, member=active_member)
        assert reg.total_headcount == 4
        assert reg.checked_in is False

        # 2. Toggle check-in at gate
        resp_checkin = client.post(reverse('events:event_check_in_toggle', args=[reg.id]))
        assert resp_checkin.status_code in [302, 303]
        reg.refresh_from_db()
        assert reg.checked_in is True

    def test_member_portal_festival_events_rsvp_flow(self, client, active_member, upcoming_festival):
        self._login_portal_member(client, active_member)

        # 1. View portal events page
        resp_page = client.get(reverse('events:portal_events'))
        assert resp_page.status_code == 200
        assert "Diwali Milan 2026" in resp_page.content.decode()

        # 2. Member RSVPs
        resp_rsvp = client.post(reverse('events:portal_rsvp', args=[upcoming_festival.id]), {
            'num_family_members': 1,
            'num_guests': 1,
            'notes': 'Vegetarian meal preference'
        })
        assert resp_rsvp.status_code in [302, 303]

        reg = EventRegistration.objects.get(event=upcoming_festival, member=active_member)
        assert reg.total_headcount == 3
        assert reg.status == RegistrationStatus.CONFIRMED

        # 3. Member cancels RSVP
        resp_cancel = client.post(reverse('events:portal_cancel_rsvp', args=[reg.id]))
        assert resp_cancel.status_code in [302, 303]
        reg.refresh_from_db()
        assert reg.status == RegistrationStatus.CANCELLED
