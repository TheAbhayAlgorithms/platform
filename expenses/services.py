import csv
import io
from decimal import Decimal
from datetime import date
from typing import List, Dict, Any, Optional
from django.db import transaction, models
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User

from expenses.models import (
    BudgetHead,
    Expense,
    ExpenseStatus,
    ExpensePaymentMode,
    ExpenseCategory,
)


def record_expense(
    category: str,
    title: str,
    payee: str,
    amount: Decimal,
    expense_date: date,
    payment_mode: str = ExpensePaymentMode.UPI,
    reference_number: str = '',
    notes: str = '',
    budget_head: Optional[BudgetHead] = None,
    submitted_by: Optional[User] = None,
    is_approved: bool = False,
    approved_by: Optional[User] = None
) -> Expense:
    """
    Validates expenditure and generates a sequential expense voucher.
    """
    if amount <= Decimal('0.00'):
        raise ValidationError("Expense amount must be greater than ₹0.00.")

    if budget_head and not budget_head.is_active:
        raise ValidationError(f"Budget head '{budget_head.name}' is inactive and cannot accept expenses.")

    status = ExpenseStatus.APPROVED if is_approved else ExpenseStatus.SUBMITTED

    with transaction.atomic():
        expense = Expense.objects.create(
            budget_head=budget_head,
            category=category,
            title=title.strip(),
            payee=payee.strip(),
            amount=amount,
            expense_date=expense_date,
            payment_mode=payment_mode,
            reference_number=reference_number.strip() if reference_number else '',
            status=status,
            submitted_by=submitted_by,
            approved_by=approved_by if is_approved else None,
            approved_at=timezone.now() if is_approved else None,
            notes=notes.strip() if notes else ''
        )
        return expense


def approve_expense(expense: Expense, user: User) -> Expense:
    """Approves a submitted expense voucher."""
    if expense.status == ExpenseStatus.APPROVED:
        return expense

    expense.status = ExpenseStatus.APPROVED
    expense.approved_by = user
    expense.approved_at = timezone.now()
    expense.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])
    return expense


def reject_expense(expense: Expense, reason: str, user: User) -> Expense:
    """Rejects an expense voucher with audit remarks."""
    expense.status = ExpenseStatus.REJECTED
    expense.rejection_reason = reason.strip()
    expense.save(update_fields=['status', 'rejection_reason', 'updated_at'])
    return expense


def get_budget_overview(fiscal_year: Optional[str] = None) -> Dict[str, Any]:
    """
    Computes macro budget metrics across all active allocation heads.
    """
    heads = BudgetHead.objects.all()
    if fiscal_year:
        heads = heads.filter(fiscal_year=fiscal_year)

    total_allocated = heads.aggregate(total=models.Sum('allocated_amount'))['total'] or Decimal('0.00')

    # Sum all approved expenses
    approved_expenses = Expense.objects.filter(status__in=[ExpenseStatus.APPROVED, ExpenseStatus.PAID])
    if fiscal_year:
        approved_expenses = approved_expenses.filter(budget_head__fiscal_year=fiscal_year)

    total_spent = approved_expenses.aggregate(total=models.Sum('amount'))['total'] or Decimal('0.00')
    remaining = total_allocated - total_spent
    utilization = round(float((total_spent / total_allocated) * 100), 1) if total_allocated > Decimal('0.00') else 0.0

    return {
        'total_allocated': total_allocated,
        'total_spent': total_spent,
        'remaining': remaining,
        'utilization': utilization,
        'is_over_budget': total_spent > total_allocated,
    }


def export_expenses_csv(queryset=None) -> str:
    """Generates a CSV ledger of expense vouchers."""
    if queryset is None:
        queryset = Expense.objects.select_related('budget_head', 'submitted_by', 'approved_by').all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'Voucher #', 'Date', 'Title / Purpose', 'Payee / Vendor', 'Category', 'Budget Head',
        'Amount (INR)', 'Payment Mode', 'Reference #', 'Status', 'Submitted By', 'Approved By'
    ])

    for exp in queryset:
        writer.writerow([
            exp.voucher_number,
            exp.expense_date.strftime('%d-%m-%Y'),
            exp.title,
            exp.payee,
            exp.get_category_display(),
            exp.budget_head.name if exp.budget_head else 'Direct Expense',
            f"{exp.amount:.2f}",
            exp.get_payment_mode_display(),
            exp.reference_number,
            exp.get_status_display(),
            exp.submitted_by.username if exp.submitted_by else '',
            exp.approved_by.username if exp.approved_by else '',
        ])

    return output.getvalue()
