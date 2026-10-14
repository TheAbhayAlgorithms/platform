from decimal import Decimal
from datetime import date
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.core.paginator import Paginator
from django.core.exceptions import ValidationError, PermissionDenied
from django.http import HttpResponse, HttpResponseForbidden
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.db import models

from accounts.decorators import admin_login_required, payment_management_required, role_required
from accounts.models import RoleChoices
from expenses.models import (
    BudgetHead,
    Expense,
    ExpenseStatus,
    ExpensePaymentMode,
    ExpenseCategory,
)
from expenses.forms import (
    ExpenseForm,
    BudgetHeadForm,
    ExpenseRejectionForm,
)
from expenses.services import (
    record_expense,
    approve_expense,
    reject_expense,
    get_budget_overview,
    export_expenses_csv,
)


@admin_login_required
def expense_list(request):
    """
    Staff ledger of all institute expenses and disbursements.
    Filterable by category, budget head, status, payment mode, and search query.
    """
    category_filter = request.GET.get('category', '').strip()
    status_filter = request.GET.get('status', '').strip()
    head_filter = request.GET.get('head', '').strip()
    search_query = request.GET.get('q', '').strip()

    expenses_qs = Expense.objects.select_related('budget_head', 'submitted_by', 'approved_by').order_by('-expense_date', '-created_at')

    if category_filter:
        expenses_qs = expenses_qs.filter(category=category_filter)
    if status_filter:
        expenses_qs = expenses_qs.filter(status=status_filter)
    if head_filter:
        expenses_qs = expenses_qs.filter(budget_head_id=head_filter)
    if search_query:
        expenses_qs = expenses_qs.filter(
            models.Q(voucher_number__icontains=search_query) |
            models.Q(title__icontains=search_query) |
            models.Q(payee__icontains=search_query) |
            models.Q(reference_number__icontains=search_query)
        )

    all_exp = Expense.objects.all()
    approved_total = all_exp.filter(status__in=[ExpenseStatus.APPROVED, ExpenseStatus.PAID]).aggregate(total=models.Sum('amount'))['total'] or Decimal('0.00')
    pending_total = all_exp.filter(status=ExpenseStatus.SUBMITTED).aggregate(total=models.Sum('amount'))['total'] or Decimal('0.00')

    counts = {
        'total': all_exp.count(),
        'approved_total': approved_total,
        'pending_total': pending_total,
        'pending_count': all_exp.filter(status=ExpenseStatus.SUBMITTED).count(),
        'rejected_count': all_exp.filter(status=ExpenseStatus.REJECTED).count(),
    }

    paginator = Paginator(expenses_qs, 15)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    profile = getattr(request.user, 'profile', None)
    can_approve = False
    can_create = False
    if profile:
        if profile.can_manage_payments():
            can_approve = True
            can_create = True
        elif profile.can_manage_events():
            can_create = True

    budget_heads = BudgetHead.objects.filter(is_active=True).order_by('name')

    context = {
        'page_obj': page_obj,
        'counts': counts,
        'category_filter': category_filter,
        'status_filter': status_filter,
        'head_filter': head_filter,
        'search_query': search_query,
        'category_choices': ExpenseCategory.choices,
        'status_choices': ExpenseStatus.choices,
        'budget_heads': budget_heads,
        'can_approve': can_approve,
        'can_create': can_create,
    }
    return render(request, 'expenses/expense_list.html', context)


@role_required([RoleChoices.SUPER_ADMIN, RoleChoices.ACCOUNTANT, RoleChoices.EVENT_MANAGER])
def expense_create(request):
    """
    Staff action to record an expenditure voucher.
    Super Admin & Accountant can auto-approve; Event Managers submit for review.
    """
    profile = getattr(request.user, 'profile', None)

    if request.method == 'POST':
        form = ExpenseForm(request.POST)
        if form.is_valid():
            can_auto_approve = profile.can_manage_payments() if profile else False
            is_approved = can_auto_approve and (request.POST.get('auto_approve') == '1')

            exp = record_expense(
                category=form.cleaned_data['category'],
                title=form.cleaned_data['title'],
                payee=form.cleaned_data['payee'],
                amount=form.cleaned_data['amount'],
                expense_date=form.cleaned_data['expense_date'],
                payment_mode=form.cleaned_data['payment_mode'],
                reference_number=form.cleaned_data['reference_number'],
                notes=form.cleaned_data['notes'],
                budget_head=form.cleaned_data['budget_head'],
                submitted_by=request.user,
                is_approved=is_approved,
                approved_by=request.user if is_approved else None
            )

            status_msg = "approved and recorded" if is_approved else "submitted for review"
            messages.success(request, f"Expense voucher {exp.voucher_number} {status_msg}.")
            return redirect('expenses:expense_detail', expense_id=exp.id)
    else:
        form = ExpenseForm(initial={'expense_date': timezone.now().date()})

    context = {
        'form': form,
        'can_auto_approve': profile.can_manage_payments() if profile else False,
    }
    return render(request, 'expenses/expense_form.html', context)


@admin_login_required
def expense_detail(request, expense_id):
    """
    Voucher audit breakdown showing payee, budget head, approval status,
    and administrative decision controls.
    """
    expense = get_object_or_404(
        Expense.objects.select_related('budget_head', 'submitted_by', 'approved_by'),
        pk=expense_id
    )

    profile = getattr(request.user, 'profile', None)
    can_approve = profile.can_manage_payments() if profile else False

    rejection_form = ExpenseRejectionForm()

    context = {
        'expense': expense,
        'can_approve': can_approve,
        'rejection_form': rejection_form,
    }
    return render(request, 'expenses/expense_detail.html', context)


@payment_management_required
@require_POST
def expense_approve(request, expense_id):
    """Staff action to approve an expense voucher."""
    expense = get_object_or_404(Expense, pk=expense_id)
    approve_expense(expense, user=request.user)
    messages.success(request, f"Expense voucher {expense.voucher_number} approved.")
    return redirect('expenses:expense_detail', expense_id=expense.id)


@payment_management_required
@require_POST
def expense_reject(request, expense_id):
    """Staff action to reject an expense voucher."""
    expense = get_object_or_404(Expense, pk=expense_id)
    form = ExpenseRejectionForm(request.POST)
    if form.is_valid():
        reason = form.cleaned_data['rejection_reason']
        reject_expense(expense, reason=reason, user=request.user)
        messages.warning(request, f"Expense voucher {expense.voucher_number} has been rejected.")
    else:
        messages.error(request, "Rejection reason is required.")
    return redirect('expenses:expense_detail', expense_id=expense.id)


@admin_login_required
def expense_export_csv(request):
    """Downloads a CSV file of the expenditures."""
    csv_data = export_expenses_csv()
    response = HttpResponse(csv_data, content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="institute_expenses_ledger.csv"'
    return response


# =========================================================================
# BUDGET HEADS & FISCAL YEAR ALLOCATION VIEWS
# =========================================================================

@admin_login_required
def budget_list(request):
    """
    Directory of fiscal year budget allocations, remaining amounts,
    and department utilization progress bars.
    """
    fiscal_year = request.GET.get('year', '2026-2027').strip()
    heads = BudgetHead.objects.filter(fiscal_year=fiscal_year).order_by('category', 'name')

    overview = get_budget_overview(fiscal_year)

    profile = getattr(request.user, 'profile', None)
    can_manage = profile.can_manage_payments() if profile else False

    context = {
        'heads': heads,
        'fiscal_year': fiscal_year,
        'overview': overview,
        'can_manage': can_manage,
    }
    return render(request, 'expenses/budget_list.html', context)


@payment_management_required
def budget_create(request):
    """Accountant / Admin action to allocate a new budget head."""
    if request.method == 'POST':
        form = BudgetHeadForm(request.POST)
        if form.is_valid():
            head = form.save()
            messages.success(request, f"Budget head '{head.name}' allocated successfully.")
            return redirect('expenses:budget_list')
    else:
        form = BudgetHeadForm(initial={'fiscal_year': '2026-2027', 'is_active': True})

    context = {
        'form': form,
        'is_edit': False,
    }
    return render(request, 'expenses/budget_form.html', context)


@payment_management_required
def budget_edit(request, budget_id):
    """Accountant / Admin action to modify an existing budget allocation."""
    head = get_object_or_404(BudgetHead, pk=budget_id)

    if request.method == 'POST':
        form = BudgetHeadForm(request.POST, instance=head)
        if form.is_valid():
            form.save()
            messages.success(request, f"Budget head '{head.name}' updated successfully.")
            return redirect('expenses:budget_list')
    else:
        form = BudgetHeadForm(instance=head)

    context = {
        'form': form,
        'head': head,
        'is_edit': True,
    }
    return render(request, 'expenses/budget_form.html', context)
