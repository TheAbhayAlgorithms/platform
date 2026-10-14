from decimal import Decimal
from django.db import models, transaction
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.exceptions import ValidationError


class ExpenseCategory(models.TextChoices):
    SPORTS_GYM = 'SPORTS_GYM', 'Sports, Tournaments & Gym'
    CULTURAL_FESTIVALS = 'CULTURAL_FESTIVALS', 'Cultural Events & Celebrations'
    MAINTENANCE_REPAIRS = 'MAINTENANCE_REPAIRS', 'Building Repairs & Maintenance'
    UTILITIES = 'UTILITIES', 'Electricity, Water & Utilities'
    CANTEEN_KITCHEN = 'CANTEEN_KITCHEN', 'Canteen Provisions & Kitchen'
    ADMIN_OFFICE = 'ADMIN_OFFICE', 'Office Supplies, Printing & Admin'
    STAFF_HONORARIUM = 'STAFF_HONORARIUM', 'Staff Salaries & Honorarium'
    OTHER = 'OTHER', 'Miscellaneous / Contingency'


class BudgetHead(models.Model):
    """
    Fiscal year budget allocation for institute operational departments
    and festival celebration programs.
    """
    name = models.CharField(
        max_length=150,
        help_text="Name of the budget allocation (e.g. Annual Sports Day 2026, Canteen Refurbishment)."
    )
    category = models.CharField(
        max_length=30,
        choices=ExpenseCategory.choices,
        default=ExpenseCategory.MAINTENANCE_REPAIRS,
        db_index=True
    )
    fiscal_year = models.CharField(
        max_length=15,
        default='2026-2027',
        help_text="Financial Year (e.g. 2026-2027)."
    )
    allocated_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Total approved budget in INR (₹)."
    )
    notes = models.TextField(
        blank=True,
        help_text="Committee approval reference, resolution number, or allocation remarks."
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Active budget head available for booking expenses."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Budget Allocation"
        verbose_name_plural = "Budget Allocations"
        ordering = ['fiscal_year', 'name']
        unique_together = ('name', 'fiscal_year')

    def __str__(self):
        return f"{self.name} ({self.fiscal_year}) - ₹{self.allocated_amount:,.2f}"

    def clean(self):
        if self.allocated_amount is not None and self.allocated_amount < Decimal('0.00'):
            raise ValidationError({'allocated_amount': "Budget allocation cannot be negative."})

    @property
    def total_spent(self) -> Decimal:
        """Sums all approved or disbursed expenses under this head."""
        agg = self.expenses.filter(
            status__in=['APPROVED', 'PAID']
        ).aggregate(total=models.Sum('amount'))['total']
        return agg or Decimal('0.00')

    @property
    def remaining_amount(self) -> Decimal:
        return self.allocated_amount - self.total_spent

    @property
    def utilization_percentage(self) -> float:
        if self.allocated_amount <= Decimal('0.00'):
            return 0.0
        return round(float((self.total_spent / self.allocated_amount) * 100), 1)

    @property
    def is_over_budget(self) -> bool:
        return self.total_spent > self.allocated_amount


class ExpensePaymentMode(models.TextChoices):
    CASH = 'CASH', 'Cash'
    UPI = 'UPI', 'UPI / QR Payment'
    NEFT_RTGS = 'NEFT_RTGS', 'Bank Transfer (NEFT / RTGS / IMPS)'
    CHEQUE = 'CHEQUE', 'Cheque'


class ExpenseStatus(models.TextChoices):
    SUBMITTED = 'SUBMITTED', 'Submitted (Pending Review)'
    APPROVED = 'APPROVED', 'Approved'
    REJECTED = 'REJECTED', 'Rejected'
    PAID = 'PAID', 'Disbursed / Paid'


class Expense(models.Model):
    """
    Institute expenditure voucher record.
    Tracks sequential voucher numbers, payee details, budget head linkage,
    payment method, and administrative approval workflow.
    """
    voucher_number = models.CharField(
        max_length=25,
        unique=True,
        db_index=True,
        help_text="Sequential expense voucher identifier (e.g. EXP-2026-00001)."
    )
    budget_head = models.ForeignKey(
        BudgetHead,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='expenses',
        help_text="Associated budget allocation."
    )
    category = models.CharField(
        max_length=30,
        choices=ExpenseCategory.choices,
        default=ExpenseCategory.MAINTENANCE_REPAIRS,
        db_index=True
    )
    title = models.CharField(
        max_length=200,
        help_text="Summary of expense (e.g. Generator diesel refill for Diwali festival)."
    )
    payee = models.CharField(
        max_length=150,
        help_text="Name of the vendor, shop, contractor, or recipient."
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Expenditure amount in INR (₹)."
    )
    expense_date = models.DateField(
        default=timezone.now,
        db_index=True,
        help_text="Date on which the expense was incurred."
    )
    payment_mode = models.CharField(
        max_length=20,
        choices=ExpensePaymentMode.choices,
        default=ExpensePaymentMode.UPI
    )
    reference_number = models.CharField(
        max_length=100,
        blank=True,
        help_text="Vendor bill / invoice #, cheque #, or UPI UTR reference."
    )
    status = models.CharField(
        max_length=20,
        choices=ExpenseStatus.choices,
        default=ExpenseStatus.SUBMITTED,
        db_index=True
    )
    submitted_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='submitted_expenses'
    )
    approved_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='approved_expenses'
    )
    approved_at = models.DateTimeField(
        null=True,
        blank=True
    )
    rejection_reason = models.TextField(
        blank=True,
        help_text="Explanation if the voucher was rejected."
    )
    notes = models.TextField(
        blank=True,
        help_text="Itemized items purchased, tax details, or committee justification."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Expense Voucher"
        verbose_name_plural = "Expense Vouchers"
        ordering = ['-expense_date', '-created_at']
        indexes = [
            models.Index(fields=['expense_date', 'category']),
            models.Index(fields=['status', 'expense_date']),
        ]

    def __str__(self):
        return f"{self.voucher_number} - {self.title} (₹{self.amount:,.2f})"

    def clean(self):
        if self.amount is not None and self.amount <= Decimal('0.00'):
            raise ValidationError({'amount': "Expense amount must be greater than ₹0.00."})

    @classmethod
    def generate_next_voucher_number(cls, year: int = None) -> str:
        """
        Thread-safe generation of next sequential expense voucher: EXP-YYYY-NNNNN.
        """
        if year is None:
            year = timezone.now().year

        prefix = f"EXP-{year}-"
        with transaction.atomic():
            latest = cls.objects.select_for_update().filter(
                voucher_number__startswith=prefix
            ).order_by('-voucher_number').first()

            if latest:
                try:
                    num_part = int(latest.voucher_number.split('-')[-1])
                    next_num = num_part + 1
                except (ValueError, IndexError):
                    next_num = 1
            else:
                next_num = 1

            return f"{prefix}{next_num:05d}"

    def save(self, *args, **kwargs):
        if not self.voucher_number:
            self.voucher_number = self.generate_next_voucher_number(
                self.expense_date.year if self.expense_date else None
            )
        super().save(*args, **kwargs)
