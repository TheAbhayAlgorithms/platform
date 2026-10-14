from decimal import Decimal
from datetime import date, timedelta
import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse
from django.core.exceptions import ValidationError

from accounts.models import UserProfile, RoleChoices
from members.models import Member, MemberStatus, DepartmentChoices
from plans.models import Plan, DiscountConcession, MemberPlanAssignment, LateFeeType, DiscountType

@pytest.fixture
def superadmin_user(db):
    user = User.objects.create_user(
        username='superadmin_m3',
        password='TestPassword123!',
        is_staff=True,
        is_superuser=True,
    )
    UserProfile.objects.create(
        user=user,
        role=RoleChoices.SUPER_ADMIN,
        phone='+919876543210',
    )
    return user


@pytest.fixture
def viewer_user(db):
    user = User.objects.create_user(
        username='viewer_m3',
        password='TestPassword123!',
        is_staff=True,
    )
    UserProfile.objects.create(
        user=user,
        role=RoleChoices.VIEWER,
        phone='+919876543213',
    )
    return user


@pytest.fixture
def sample_member(db):
    return Member.objects.create(
        name='Harish Chandra',
        phone='9876577001',
        department=DepartmentChoices.ENGINEERING,
        status=MemberStatus.ACTIVE,
    )


@pytest.fixture
def annual_plan(db):
    return Plan.objects.create(
        name='Standard Annual Plan',
        fee=Decimal('3000.00'),
        duration_months=12,
        grace_period_days=15,
        late_fee_type=LateFeeType.FLAT,
        late_fee_amount=Decimal('100.00'),
        is_active=True,
    )


@pytest.mark.django_db
class TestPlanDateMath:
    """Verifies end-date calculation across normal, month-end, and leap-year cases."""

    def test_standard_annual_and_quarterly_end_dates(self):
        plan_annual = Plan(name='Annual', fee=3000, duration_months=12)
        # 01-Jan-2026 to 31-Dec-2026
        assert plan_annual.compute_end_date(date(2026, 1, 1)) == date(2026, 12, 31)

        plan_quarterly = Plan(name='Quarterly', fee=1000, duration_months=3)
        # 01-Apr-2026 to 30-Jun-2026
        assert plan_quarterly.compute_end_date(date(2026, 4, 1)) == date(2026, 6, 30)

    def test_leap_year_february_calculations(self):
        plan_monthly = Plan(name='Monthly', fee=500, duration_months=1)
        
        # In leap year 2024: 01-Feb-2024 to 29-Feb-2024
        assert plan_monthly.compute_end_date(date(2024, 2, 1)) == date(2024, 2, 29)

        # In non-leap year 2025: 01-Feb-2025 to 28-Feb-2025
        assert plan_monthly.compute_end_date(date(2025, 2, 1)) == date(2025, 2, 28)

        # Leap day start: 29-Feb-2024 + 1 year (to non-leap 2025)
        plan_annual = Plan(name='Annual', fee=3000, duration_months=12)
        assert plan_annual.compute_end_date(date(2024, 2, 29)) == date(2025, 2, 28)

    def test_month_end_start_dates(self):
        plan_monthly = Plan(name='Monthly', fee=500, duration_months=1)
        # Start on Jan 31 in leap year 2024 -> covers whole next month through Feb 29
        assert plan_monthly.compute_end_date(date(2024, 1, 31)) == date(2024, 2, 29)

        # Start on Jan 31 in non-leap year 2025 -> covers through Feb 28
        assert plan_monthly.compute_end_date(date(2025, 1, 31)) == date(2025, 2, 28)


@pytest.mark.django_db
class TestDiscountAndLateFeeMath:
    """Verifies discount percentage/flat arithmetic and late fee calculations."""

    def test_percentage_discount_calculation(self):
        disc50 = DiscountConcession(
            name='50% Concession',
            discount_type=DiscountType.PERCENTAGE,
            discount_value=Decimal('50.00'),
            is_active=True,
        )
        assert disc50.calculate_discount_amount(Decimal('3000.00')) == Decimal('1500.00')
        assert disc50.calculate_discount_amount(Decimal('1000.00')) == Decimal('500.00')

    def test_flat_discount_capped_at_base_fee(self):
        disc_flat = DiscountConcession(
            name='Flat ₹400',
            discount_type=DiscountType.FLAT,
            discount_value=Decimal('400.00'),
            is_active=True,
        )
        assert disc_flat.calculate_discount_amount(Decimal('1000.00')) == Decimal('400.00')
        # If fee is smaller than discount, it is capped at the fee amount (never negative)
        assert disc_flat.calculate_discount_amount(Decimal('300.00')) == Decimal('300.00')

    def test_late_fee_flat_and_per_day_calculation(self):
        # Flat late fee: ₹100 after 15 days grace
        plan_flat = Plan(
            name='Flat Late Plan',
            fee=Decimal('2000.00'),
            grace_period_days=15,
            late_fee_type=LateFeeType.FLAT,
            late_fee_amount=Decimal('100.00'),
        )
        end_date = date(2026, 1, 1)
        
        # During grace period (e.g. 10 days after end): 0 late fee
        assert plan_flat.calculate_late_fee(date(2026, 1, 11), end_date) == Decimal('0.00')
        # On last day of grace period (day 15): 0 late fee
        assert plan_flat.calculate_late_fee(date(2026, 1, 16), end_date) == Decimal('0.00')
        # Past grace period (day 16): flat ₹100
        assert plan_flat.calculate_late_fee(date(2026, 1, 17), end_date) == Decimal('100.00')

        # Per-day late fee: ₹10/day after 5 days grace
        plan_per_day = Plan(
            name='Per Day Plan',
            fee=Decimal('1000.00'),
            grace_period_days=5,
            late_fee_type=LateFeeType.PER_DAY,
            late_fee_amount=Decimal('10.00'),
        )
        grace_end = end_date + timedelta(days=5)  # 2026-01-06
        # 3 days overdue past grace
        assert plan_per_day.calculate_late_fee(grace_end + timedelta(days=3), end_date) == Decimal('30.00')


@pytest.mark.django_db
class TestPlanAssignmentAndImmutability:
    """
    Tests assigning plans, deactivation checks, and fee immutability:
    Changing a plan's fee does NOT alter already-assigned fees!
    """

    def test_deactivated_plan_cannot_be_assigned(self, sample_member, annual_plan):
        annual_plan.is_active = False
        annual_plan.save()

        assignment = MemberPlanAssignment(
            member=sample_member,
            plan=annual_plan,
            start_date=date(2026, 1, 1),
        )
        with pytest.raises(ValidationError):
            assignment.clean()

    def test_changing_plan_fee_does_not_alter_already_assigned_fees(self, sample_member, annual_plan):
        """
        Critical business requirement:
        If an assignment was created at ₹3,000, updating the plan fee to ₹3,500
        leaves the existing assignment at ₹3,000.
        """
        assignment = MemberPlanAssignment.objects.create(
            member=sample_member,
            plan=annual_plan,
            start_date=date(2026, 1, 1),
        )
        assert assignment.base_fee == Decimal('3000.00')
        assert assignment.final_fee == Decimal('3000.00')

        # Institute increases Annual Plan fee to ₹3,500
        annual_plan.fee = Decimal('3500.00')
        annual_plan.save()

        # Reload assignment from DB: fee must remain exactly ₹3,000.00!
        assignment.refresh_from_db()
        assert assignment.base_fee == Decimal('3000.00')
        assert assignment.final_fee == Decimal('3000.00')

    def test_assignment_with_discount_applies_correct_final_fee(self, sample_member, annual_plan):
        disc = DiscountConcession.objects.create(
            name='Senior 50%',
            discount_type=DiscountType.PERCENTAGE,
            discount_value=Decimal('50.00'),
            is_active=True,
        )
        assignment = MemberPlanAssignment.objects.create(
            member=sample_member,
            plan=annual_plan,
            discount=disc,
            start_date=date(2026, 1, 1),
        )
        assert assignment.base_fee == Decimal('3000.00')
        assert assignment.discount_amount == Decimal('1500.00')
        assert assignment.final_fee == Decimal('1500.00')


@pytest.mark.django_db
class TestPlanViewsAndPermissions:
    """Verifies plan management views, forms, and permission enforcement."""

    def test_viewer_is_read_only(self, viewer_user, sample_member, annual_plan):
        client = Client()
        client.force_login(viewer_user)

        # Viewer can view plans
        res_list = client.get(reverse('plans:plan_list'))
        assert res_list.status_code == 200

        # Viewer is denied from creating or editing plans
        res_add = client.get(reverse('plans:plan_create'))
        assert res_add.status_code == 403

        res_edit = client.get(reverse('plans:plan_edit', kwargs={'plan_id': annual_plan.id}))
        assert res_edit.status_code == 403

        res_assign = client.get(reverse('plans:member_assign', kwargs={'member_id': sample_member.id}))
        assert res_assign.status_code == 403

    def test_super_admin_create_and_assign_plan_flow(self, superadmin_user, sample_member):
        client = Client()
        client.force_login(superadmin_user)

        # Create new 6-month plan
        post_plan = {
            'name': 'Special 6-Month Plan',
            'fee': '1500.00',
            'duration_months': 6,
            'duration_days': 0,
            'grace_period_days': 10,
            'late_fee_type': LateFeeType.FLAT,
            'late_fee_amount': '50.00',
            'is_active': True,
        }
        res1 = client.post(reverse('plans:plan_create'), post_plan)
        assert res1.status_code == 302
        new_plan = Plan.objects.get(name='Special 6-Month Plan')

        # Assign to member
        post_assign = {
            'plan': new_plan.id,
            'start_date': '2026-05-01',
        }
        res2 = client.post(reverse('plans:member_assign', kwargs={'member_id': sample_member.id}), post_assign)
        assert res2.status_code == 302

        assignment = sample_member.plan_assignments.first()
        assert assignment.plan == new_plan
        assert assignment.start_date == date(2026, 5, 1)
        assert assignment.end_date == date(2026, 10, 31)
        assert assignment.final_fee == Decimal('1500.00')
