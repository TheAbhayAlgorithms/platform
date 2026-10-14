from datetime import date, timedelta
from decimal import Decimal
import pytest

from django.test import Client
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from accounts.models import UserProfile, RoleChoices
from expenses.models import (
    BudgetHead,
    Expense,
    ExpenseCategory,
    ExpensePaymentMode,
    ExpenseStatus,
)
from expenses.forms import ExpenseForm, BudgetHeadForm, ExpenseRejectionForm
from expenses.services import (
    record_expense,
    approve_expense,
    reject_expense,
    get_budget_overview,
    export_expenses_csv,
)


@pytest.fixture
def superadmin_user(db):
    user = User.objects.create_user(username="superadmin_user", password="password123")
    UserProfile.objects.create(user=user, role=RoleChoices.SUPER_ADMIN)
    return user


@pytest.fixture
def accountant_user(db):
    user = User.objects.create_user(username="acct_user", password="password123")
    UserProfile.objects.create(user=user, role=RoleChoices.ACCOUNTANT)
    return user


@pytest.fixture
def event_manager_user(db):
    user = User.objects.create_user(username="event_mgr_user", password="password123")
    UserProfile.objects.create(user=user, role=RoleChoices.EVENT_MANAGER)
    return user


@pytest.fixture
def viewer_user(db):
    user = User.objects.create_user(username="view_user", password="password123")
    UserProfile.objects.create(user=user, role=RoleChoices.VIEWER)
    return user


@pytest.fixture
def sports_budget(db):
    return BudgetHead.objects.create(
        name="Annual Sports Day 2026",
        category=ExpenseCategory.SPORTS_GYM,
        fiscal_year="2026-2027",
        allocated_amount=Decimal('50000.00'),
        notes="Sanctioned by Managing Committee meeting #4",
        is_active=True
    )


@pytest.fixture
def maintenance_budget(db):
    return BudgetHead.objects.create(
        name="Building & Electrical Maintenance",
        category=ExpenseCategory.MAINTENANCE_REPAIRS,
        fiscal_year="2026-2027",
        allocated_amount=Decimal('100000.00'),
        notes="General campus upkeep",
        is_active=True
    )


# =========================================================================
# 1. BUDGET HEAD MODEL & MATH TESTS
# =========================================================================

@pytest.mark.django_db
def test_budget_head_creation_and_clean():
    head = BudgetHead(
        name="Invalid Budget",
        allocated_amount=Decimal('-500.00')
    )
    with pytest.raises(ValidationError):
        head.clean()


@pytest.mark.django_db
def test_budget_math_and_utilization(sports_budget, superadmin_user):
    today = timezone.now().date()
    assert sports_budget.total_spent == Decimal('0.00')
    assert sports_budget.remaining_amount == Decimal('50000.00')
    assert sports_budget.utilization_percentage == 0.0
    assert sports_budget.is_over_budget is False

    # Record first approved expense
    record_expense(
        category=ExpenseCategory.SPORTS_GYM,
        title="Cricket equipment kit",
        payee="Metro Sports Mart",
        amount=Decimal('20000.00'),
        expense_date=today,
        budget_head=sports_budget,
        submitted_by=superadmin_user,
        is_approved=True,
        approved_by=superadmin_user
    )

    sports_budget.refresh_from_db()
    assert sports_budget.total_spent == Decimal('20000.00')
    assert sports_budget.remaining_amount == Decimal('30000.00')
    assert sports_budget.utilization_percentage == 40.0
    assert sports_budget.is_over_budget is False

    # Record second expense causing over-budget
    record_expense(
        category=ExpenseCategory.SPORTS_GYM,
        title="Tournament trophies and sound",
        payee="Royal Awards",
        amount=Decimal('35000.00'),
        expense_date=today,
        budget_head=sports_budget,
        submitted_by=superadmin_user,
        is_approved=True,
        approved_by=superadmin_user
    )

    sports_budget.refresh_from_db()
    assert sports_budget.total_spent == Decimal('55000.00')
    assert sports_budget.remaining_amount == Decimal('-5000.00')
    assert sports_budget.utilization_percentage == 110.0
    assert sports_budget.is_over_budget is True


# =========================================================================
# 2. SEQUENTIAL VOUCHER NUMBERS & SERVICES
# =========================================================================

@pytest.mark.django_db
def test_sequential_voucher_number_generation(superadmin_user):
    today = timezone.now().date()
    e1 = record_expense(
        category=ExpenseCategory.ADMIN_OFFICE,
        title="A4 Paper and printer ink",
        payee="Stationery Mart",
        amount=Decimal('1500.00'),
        expense_date=today,
        submitted_by=superadmin_user
    )
    e2 = record_expense(
        category=ExpenseCategory.UTILITIES,
        title="Diesel for backup generator",
        payee="Indian Oil Fuel Station",
        amount=Decimal('4500.00'),
        expense_date=today,
        submitted_by=superadmin_user
    )

    year = today.year
    assert e1.voucher_number == f"EXP-{year}-00001"
    assert e2.voucher_number == f"EXP-{year}-00002"


@pytest.mark.django_db
def test_record_expense_invalid_amount():
    today = timezone.now().date()
    with pytest.raises(ValidationError, match="greater than"):
        record_expense(
            category=ExpenseCategory.ADMIN_OFFICE,
            title="Zero test",
            payee="Vendor",
            amount=Decimal('0.00'),
            expense_date=today
        )


@pytest.mark.django_db
def test_record_expense_inactive_budget_head(superadmin_user):
    inactive_head = BudgetHead.objects.create(
        name="Decommissioned Head",
        allocated_amount=Decimal('10000.00'),
        is_active=False
    )
    today = timezone.now().date()
    with pytest.raises(ValidationError, match="inactive"):
        record_expense(
            category=ExpenseCategory.OTHER,
            title="Attempt on inactive",
            payee="Vendor",
            amount=Decimal('1000.00'),
            expense_date=today,
            budget_head=inactive_head
        )


# =========================================================================
# 3. APPROVAL & REJECTION WORKFLOW
# =========================================================================

@pytest.mark.django_db
def test_approve_expense_service(superadmin_user, accountant_user):
    today = timezone.now().date()
    exp = record_expense(
        category=ExpenseCategory.MAINTENANCE_REPAIRS,
        title="Plumbing valve replacement",
        payee="Apex Plumbers",
        amount=Decimal('2800.00'),
        expense_date=today,
        submitted_by=superadmin_user,
        is_approved=False
    )
    assert exp.status == ExpenseStatus.SUBMITTED

    approved = approve_expense(exp, user=accountant_user)
    assert approved.status == ExpenseStatus.APPROVED
    assert approved.approved_by == accountant_user
    assert approved.approved_at is not None


@pytest.mark.django_db
def test_reject_expense_service(superadmin_user, accountant_user):
    today = timezone.now().date()
    exp = record_expense(
        category=ExpenseCategory.OTHER,
        title="Unauthorized catering bill",
        payee="Private Caterer",
        amount=Decimal('8000.00'),
        expense_date=today,
        submitted_by=superadmin_user,
        is_approved=False
    )

    rejected = reject_expense(exp, reason="Prior sanction from Treasurer not attached", user=accountant_user)
    assert rejected.status == ExpenseStatus.REJECTED
    assert "Prior sanction" in rejected.rejection_reason


# =========================================================================
# 4. BUDGET OVERVIEW & EXPORTS
# =========================================================================

@pytest.mark.django_db
def test_get_budget_overview_and_csv_export(sports_budget, maintenance_budget, superadmin_user):
    today = timezone.now().date()
    record_expense(
        category=ExpenseCategory.SPORTS_GYM,
        title="Table tennis balls and nets",
        payee="Sports World",
        amount=Decimal('5000.00'),
        expense_date=today,
        budget_head=sports_budget,
        submitted_by=superadmin_user,
        is_approved=True,
        approved_by=superadmin_user
    )

    overview = get_budget_overview("2026-2027")
    assert overview['total_allocated'] == Decimal('150000.00')
    assert overview['total_spent'] == Decimal('5000.00')
    assert overview['remaining'] == Decimal('145000.00')

    csv_data = export_expenses_csv()
    assert "Table tennis balls and nets" in csv_data
    assert "EXP-" in csv_data
    assert "Sports World" in csv_data


# =========================================================================
# 5. STAFF VIEWS & RBAC PERMISSION TESTS
# =========================================================================

@pytest.mark.django_db
def test_expense_list_view_access(accountant_user, event_manager_user, viewer_user):
    client = Client()
    url = reverse('expenses:expense_list')

    # Unauthenticated redirect
    assert client.get(url).status_code == 302

    # Accountant allowed
    client.force_login(accountant_user)
    resp = client.get(url)
    assert resp.status_code == 200
    assert "Institute Expenditures &amp; Vouchers" in resp.content.decode()

    # Event Manager allowed
    client.force_login(event_manager_user)
    assert client.get(url).status_code == 200

    # Viewer allowed read-only
    client.force_login(viewer_user)
    assert client.get(url).status_code == 200


@pytest.mark.django_db
def test_expense_create_rbac(sports_budget, accountant_user, event_manager_user, viewer_user):
    client = Client()
    url = reverse('expenses:expense_create')

    # Viewer forbidden (403)
    client.force_login(viewer_user)
    assert client.get(url).status_code == 403

    # Event Manager can record submitted expense
    client.force_login(event_manager_user)
    assert client.get(url).status_code == 200

    today = timezone.now().date()
    post_data = {
        'title': "Festival sound setup advance",
        'category': ExpenseCategory.CULTURAL_FESTIVALS,
        'budget_head': sports_budget.id,
        'payee': "Soundcraft Audio",
        'amount': '12000.00',
        'expense_date': today.strftime('%Y-%m-%d'),
        'payment_mode': ExpensePaymentMode.UPI,
        'reference_number': "UPI-77441122",
        'notes': "50% advance for festive stage",
    }
    resp = client.post(url, post_data)
    assert resp.status_code == 302

    exp = Expense.objects.get(title="Festival sound setup advance")
    assert exp.status == ExpenseStatus.SUBMITTED
    assert exp.amount == Decimal('12000.00')


@pytest.mark.django_db
def test_expense_approval_and_rejection_rbac(superadmin_user, accountant_user, event_manager_user, viewer_user):
    today = timezone.now().date()
    exp = record_expense(
        category=ExpenseCategory.ADMIN_OFFICE,
        title="Annual software backup drive",
        payee="Tech Hardware",
        amount=Decimal('3500.00'),
        expense_date=today,
        submitted_by=superadmin_user,
        is_approved=False
    )

    client = Client()
    approve_url = reverse('expenses:expense_approve', kwargs={'expense_id': exp.id})
    reject_url = reverse('expenses:expense_reject', kwargs={'expense_id': exp.id})

    # Viewer forbidden
    client.force_login(viewer_user)
    assert client.post(approve_url).status_code == 403
    assert client.post(reject_url, {'rejection_reason': 'Test'}).status_code == 403

    # Event Manager forbidden from approval
    client.force_login(event_manager_user)
    assert client.post(approve_url).status_code == 403

    # Accountant allowed to approve
    client.force_login(accountant_user)
    resp = client.post(approve_url)
    assert resp.status_code == 302
    exp.refresh_from_db()
    assert exp.status == ExpenseStatus.APPROVED


@pytest.mark.django_db
def test_budget_management_rbac(sports_budget, accountant_user, event_manager_user, viewer_user):
    client = Client()
    create_url = reverse('expenses:budget_create')
    edit_url = reverse('expenses:budget_edit', kwargs={'budget_id': sports_budget.id})

    # Viewer & Event Manager forbidden from creating/editing budgets
    client.force_login(viewer_user)
    assert client.get(create_url).status_code == 403
    assert client.get(edit_url).status_code == 403

    client.force_login(event_manager_user)
    assert client.get(create_url).status_code == 403

    # Accountant allowed
    client.force_login(accountant_user)
    assert client.get(create_url).status_code == 200
    assert client.get(edit_url).status_code == 200

    # Create new budget head POST
    post_data = {
        'name': "Library Books & Periodicals",
        'category': ExpenseCategory.ADMIN_OFFICE,
        'fiscal_year': "2026-2027",
        'allocated_amount': '25000.00',
        'notes': "Approved for quarterly procurement",
        'is_active': True,
    }
    resp = client.post(create_url, post_data)
    assert resp.status_code == 302
    assert BudgetHead.objects.filter(name="Library Books & Periodicals").exists()
