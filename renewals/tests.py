from decimal import Decimal
from datetime import date, timedelta
import pytest
from freezegun import freeze_time
from django.urls import reverse
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.management import call_command
from io import StringIO

from accounts.models import UserProfile, RoleChoices
from members.models import Member, MemberStatus, DepartmentChoices
from plans.models import Plan, DiscountConcession, DiscountType, MemberPlanAssignment
from payments.models import Payment, PaymentMode, PaymentStatus
from renewals.models import RenewalRecord
from renewals.services import (
    calculate_renewal_dates,
    process_member_renewal,
    process_auto_expiry,
    get_renewal_dashboard_data,
)


@pytest.fixture
def superadmin_user(db):
    user = User.objects.create_user(username='superadmin', password='Password@123', email='admin@railclub.test')
    UserProfile.objects.create(user=user, role=RoleChoices.SUPER_ADMIN, phone='+919876543210')
    return user


@pytest.fixture
def accountant_user(db):
    user = User.objects.create_user(username='accountant', password='Password@123', email='acct@railclub.test')
    UserProfile.objects.create(user=user, role=RoleChoices.ACCOUNTANT, phone='+919876543211')
    return user


@pytest.fixture
def eventmanager_user(db):
    user = User.objects.create_user(username='eventmgr', password='Password@123', email='event@railclub.test')
    UserProfile.objects.create(user=user, role=RoleChoices.EVENT_MANAGER, phone='+919876543212')
    return user


@pytest.fixture
def viewer_user(db):
    user = User.objects.create_user(username='viewer', password='Password@123', email='view@railclub.test')
    UserProfile.objects.create(user=user, role=RoleChoices.VIEWER, phone='+919876543213')
    return user


@pytest.fixture
def standard_plan(db):
    return Plan.objects.create(
        name="Annual Membership 2026",
        fee=Decimal('2400.00'),
        duration_months=12,
        grace_period_days=15,
        is_active=True
    )


@pytest.fixture
def quarterly_plan(db):
    return Plan.objects.create(
        name="Quarterly Plan",
        fee=Decimal('800.00'),
        duration_months=3,
        grace_period_days=7,
        is_active=True
    )


@pytest.fixture
def no_grace_plan(db):
    return Plan.objects.create(
        name="Festival Zero Grace Plan",
        fee=Decimal('500.00'),
        duration_months=1,
        grace_period_days=0,
        is_active=True
    )


@pytest.fixture
def discount_concession(db):
    return DiscountConcession.objects.create(
        name="Railway Senior Concession",
        discount_type=DiscountType.FLAT,
        discount_value=Decimal('400.00'),
        is_active=True
    )


@pytest.fixture
def active_member(db):
    return Member.objects.create(
        name="Rajesh Sharma",
        phone="+919876500001",
        employee_id="ER12345",
        department=DepartmentChoices.OPERATING,
        status=MemberStatus.ACTIVE
    )


@pytest.mark.django_db
class TestRenewalDateMath:
    def test_early_renewal_extends_from_previous_end_date(self, active_member, standard_plan):
        """If renewed before current plan expires, validity starts from previous end date + 1 day."""
        today = date(2026, 6, 1)
        current_end = date(2026, 12, 31)

        MemberPlanAssignment.objects.create(
            member=active_member,
            plan=standard_plan,
            start_date=date(2026, 1, 1),
            end_date=current_end,
            is_current=True
        )

        dates = calculate_renewal_dates(active_member, standard_plan, as_of_date=today)
        assert dates['is_early_renewal'] is True
        assert dates['new_start_date'] == date(2027, 1, 1)
        assert dates['new_end_date'] == date(2027, 12, 31)

    def test_expired_member_renewal_starts_today(self, active_member, standard_plan):
        """If renewed after current plan has already expired, validity starts today, not backdated."""
        today = date(2026, 6, 1)
        current_end = date(2026, 3, 31)  # Expired 2 months ago

        MemberPlanAssignment.objects.create(
            member=active_member,
            plan=standard_plan,
            start_date=date(2025, 4, 1),
            end_date=current_end,
            is_current=True
        )

        dates = calculate_renewal_dates(active_member, standard_plan, as_of_date=today)
        assert dates['is_early_renewal'] is False
        assert dates['new_start_date'] == today
        assert dates['new_end_date'] == standard_plan.compute_end_date(today)

    def test_member_without_assignment_starts_today(self, active_member, standard_plan):
        today = date(2026, 1, 15)
        dates = calculate_renewal_dates(active_member, standard_plan, as_of_date=today)
        assert dates['new_start_date'] == today
        assert dates['new_end_date'] == standard_plan.compute_end_date(today)


@pytest.mark.django_db
class TestRenewalExecution:
    def test_process_member_renewal_lifecycle(self, active_member, standard_plan, quarterly_plan, superadmin_user):
        """
        Tests full renewal execution:
        - Demotes old assignment to is_current=False
        - Creates new assignment with is_current=True
        - Sets member status to DUE until paid
        - Generates RenewalRecord audit log
        """
        today = date(2026, 10, 1)
        old_assignment = MemberPlanAssignment.objects.create(
            member=active_member,
            plan=standard_plan,
            start_date=date(2025, 10, 1),
            end_date=date(2026, 9, 30),
            is_current=True
        )

        new_assignment, renewal_record = process_member_renewal(
            member=active_member,
            renewed_by=superadmin_user,
            target_plan=quarterly_plan,
            notes="Renewed to Quarterly Plan",
            as_of_date=today
        )

        old_assignment.refresh_from_db()
        active_member.refresh_from_db()

        assert old_assignment.is_current is False
        assert new_assignment.is_current is True
        assert new_assignment.plan == quarterly_plan
        assert new_assignment.final_fee == Decimal('800.00')
        assert active_member.status == MemberStatus.DUE

        # Verify audit record
        assert renewal_record.member == active_member
        assert renewal_record.renewed_by == superadmin_user
        assert renewal_record.previous_assignment == old_assignment
        assert renewal_record.new_assignment == new_assignment
        assert renewal_record.fee_charged == Decimal('800.00')
        assert renewal_record.notes == "Renewed to Quarterly Plan"

    def test_renewal_with_discount_applied(self, active_member, standard_plan, discount_concession, superadmin_user):
        """Checks discount application during renewal cycle."""
        today = date(2026, 1, 1)
        new_assignment, renewal = process_member_renewal(
            member=active_member,
            renewed_by=superadmin_user,
            target_plan=standard_plan,
            discount=discount_concession,
            as_of_date=today
        )

        assert new_assignment.base_fee == Decimal('2400.00')
        assert new_assignment.discount_amount == Decimal('400.00')
        assert new_assignment.final_fee == Decimal('2000.00')
        assert renewal.fee_charged == Decimal('2000.00')

    def test_prevent_double_renewal_clicks(self, active_member, standard_plan, superadmin_user):
        """Consecutive rapid clicks should be blocked if a future renewal cycle has already been created."""
        today = date(2026, 1, 1)
        process_member_renewal(
            member=active_member,
            renewed_by=superadmin_user,
            target_plan=standard_plan,
            as_of_date=today
        )

        # Attempting renewal on same day with the same start date must be rejected
        with pytest.raises(ValidationError):
            process_member_renewal(
                member=active_member,
                renewed_by=superadmin_user,
                target_plan=standard_plan,
                as_of_date=today
            )


@pytest.mark.django_db
class TestAutoExpiryWithFreezeGun:
    def test_active_member_within_validity_not_expired(self, active_member, standard_plan):
        """Member whose validity has not lapsed remains Active."""
        MemberPlanAssignment.objects.create(
            member=active_member,
            plan=standard_plan,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            grace_period_days=15,
            is_current=True
        )

        with freeze_time("2026-06-15"):
            results = process_auto_expiry()
            active_member.refresh_from_db()
            assert active_member.status == MemberStatus.ACTIVE
            assert results['expired_count'] == 0
            assert results['active_valid_count'] == 1

    def test_member_in_grace_period_not_expired(self, active_member, standard_plan):
        """Member past end date but inside grace period is NOT marked Expired."""
        MemberPlanAssignment.objects.create(
            member=active_member,
            plan=standard_plan,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
            grace_period_days=15,  # Grace ends 2026-01-15
            is_current=True
        )

        with freeze_time("2026-01-10"):
            results = process_auto_expiry()
            active_member.refresh_from_db()
            assert active_member.status == MemberStatus.ACTIVE
            assert results['expired_count'] == 0
            assert results['in_grace_count'] == 1

    def test_member_past_grace_period_transitions_to_expired(self, active_member, standard_plan):
        """Member past validity AND grace period is marked Expired."""
        MemberPlanAssignment.objects.create(
            member=active_member,
            plan=standard_plan,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
            grace_period_days=15,  # Grace ends 2026-01-15
            is_current=True
        )

        with freeze_time("2026-01-16"):
            results = process_auto_expiry()
            active_member.refresh_from_db()
            assert active_member.status == MemberStatus.EXPIRED
            assert results['expired_count'] == 1
            assert active_member.membership_id in results['expired_member_ids']

    def test_zero_grace_period_expires_immediately(self, active_member, no_grace_plan):
        """Member with zero grace period plan expires immediately on the day after end date."""
        MemberPlanAssignment.objects.create(
            member=active_member,
            plan=no_grace_plan,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
            grace_period_days=0,
            is_current=True
        )

        with freeze_time("2026-02-01"):
            results = process_auto_expiry()
            active_member.refresh_from_db()
            assert active_member.status == MemberStatus.EXPIRED
            assert results['expired_count'] == 1

    def test_management_command_expire_memberships(self, active_member, standard_plan):
        """Tests the expire_memberships management command execution."""
        MemberPlanAssignment.objects.create(
            member=active_member,
            plan=standard_plan,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
            grace_period_days=15,
            is_current=True
        )

        out = StringIO()
        call_command('expire_memberships', '--date', '2026-02-01', stdout=out)
        output = out.getvalue()
        assert "Expiry sweep completed successfully" in output
        assert "Transitioned to EXPIRED: 1" in output

        active_member.refresh_from_db()
        assert active_member.status == MemberStatus.EXPIRED


@pytest.mark.django_db
class TestRenewalViewsAndPermissions:
    def test_dashboard_filtering_and_counts(self, client, viewer_user, active_member, standard_plan):
        """Tests dashboard renders correct counts and milestones."""
        client.force_login(viewer_user)
        session = client.session
        session['user_id'] = viewer_user.id
        session['otp_verified'] = True
        session.save()

        # Member with end date in 5 days
        MemberPlanAssignment.objects.create(
            member=active_member,
            plan=standard_plan,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 10, 19),  # 5 days from 2026-10-14
            is_current=True
        )

        with freeze_time("2026-10-14"):
            resp = client.get(reverse('renewals:renewal_list'))
            assert resp.status_code == 200
            assert resp.context['counts']['within_7'] >= 1
            assert active_member.name in resp.content.decode()

    def test_super_admin_can_execute_one_click_renewal(self, client, superadmin_user, active_member, standard_plan):
        client.force_login(superadmin_user)
        session = client.session
        session['user_id'] = superadmin_user.id
        session['otp_verified'] = True
        session.save()

        MemberPlanAssignment.objects.create(
            member=active_member,
            plan=standard_plan,
            start_date=date(2025, 10, 1),
            end_date=date(2026, 9, 30),
            is_current=True
        )

        url = reverse('renewals:one_click_renew', args=[active_member.id])
        resp = client.post(url)
        assert resp.status_code in [302, 303]

        active_member.refresh_from_db()
        assert active_member.status == MemberStatus.DUE
        assert active_member.plan_assignments.count() == 2
        assert RenewalRecord.objects.filter(member=active_member).count() == 1

    def test_accountant_can_process_custom_renewal(self, client, accountant_user, active_member, standard_plan, quarterly_plan):
        client.force_login(accountant_user)
        session = client.session
        session['user_id'] = accountant_user.id
        session['otp_verified'] = True
        session.save()

        MemberPlanAssignment.objects.create(
            member=active_member,
            plan=standard_plan,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
            is_current=True
        )

        url = reverse('renewals:renew_member', args=[active_member.id])
        resp = client.post(url, {
            'plan': quarterly_plan.id,
            'discount': '',
            'notes': 'Accountant custom renewal'
        })
        assert resp.status_code in [302, 303]

        current = active_member.plan_assignments.filter(is_current=True).first()
        assert current.plan == quarterly_plan

    def test_viewer_denied_from_executing_renewal(self, client, viewer_user, active_member, standard_plan):
        client.force_login(viewer_user)
        session = client.session
        session['user_id'] = viewer_user.id
        session['otp_verified'] = True
        session.save()

        MemberPlanAssignment.objects.create(
            member=active_member,
            plan=standard_plan,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
            is_current=True
        )

        url = reverse('renewals:one_click_renew', args=[active_member.id])
        resp = client.post(url)
        assert resp.status_code == 403  # Forbidden

    def test_event_manager_denied_from_auto_expiry_sweep(self, client, eventmanager_user):
        client.force_login(eventmanager_user)
        session = client.session
        session['user_id'] = eventmanager_user.id
        session['otp_verified'] = True
        session.save()

        url = reverse('renewals:run_auto_expiry')
        resp = client.post(url)
        assert resp.status_code == 403

    def test_member_renewal_history_view(self, client, viewer_user, active_member, standard_plan):
        client.force_login(viewer_user)
        session = client.session
        session['user_id'] = viewer_user.id
        session['otp_verified'] = True
        session.save()

        MemberPlanAssignment.objects.create(
            member=active_member,
            plan=standard_plan,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
            is_current=True
        )

        url = reverse('renewals:member_history', args=[active_member.id])
        resp = client.get(url)
        assert resp.status_code == 200
        assert active_member.name in resp.content.decode()
        assert standard_plan.name in resp.content.decode()
