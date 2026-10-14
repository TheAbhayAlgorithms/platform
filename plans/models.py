from decimal import Decimal
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
from django.db import models, transaction
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.exceptions import ValidationError

class LateFeeType(models.TextChoices):
    NONE = 'NONE', 'No Late Fee'
    FLAT = 'FLAT', 'Flat Penalty'
    PER_DAY = 'PER_DAY', 'Per-Day Penalty'


class DiscountType(models.TextChoices):
    PERCENTAGE = 'PERCENTAGE', 'Percentage Discount (%)'
    FLAT = 'FLAT', 'Flat Amount Discount (₹)'


class Plan(models.Model):
    """
    Membership Plan configuration defining fee structure,
    duration, validity rules, grace period, and late fee policies.
    """
    name = models.CharField(
        max_length=100,
        unique=True,
        help_text="Plan Name (e.g., Annual, Half-Yearly, Quarterly, Festival-Only, Custom)."
    )
    description = models.TextField(
        blank=True,
        help_text="Plan description, eligible privileges, and festival benefits."
    )
    fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Standard membership fee in INR (₹)."
    )
    duration_months = models.PositiveIntegerField(
        default=12,
        help_text="Validity duration in calendar months (e.g. 12 for Annual, 6 for Half-Yearly)."
    )
    duration_days = models.PositiveIntegerField(
        default=0,
        help_text="Additional duration in days (used for custom or short-term event plans)."
    )
    grace_period_days = models.PositiveIntegerField(
        default=15,
        help_text="Grace period days after expiry before late fees or suspension applies."
    )
    late_fee_type = models.CharField(
        max_length=20,
        choices=LateFeeType.choices,
        default=LateFeeType.NONE,
        help_text="Late fee calculation type."
    )
    late_fee_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Late fee penalty amount in INR (flat amount or per-day rate)."
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Deactivated plans cannot be newly assigned to members."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Membership Plan"
        verbose_name_plural = "Membership Plans"
        ordering = ['fee', 'duration_months']

    def __str__(self):
        status_suffix = "" if self.is_active else " (Deactivated)"
        return f"{self.name} - ₹{self.fee:,.2f} ({self.duration_display}){status_suffix}"

    @property
    def duration_display(self) -> str:
        parts = []
        if self.duration_months:
            parts.append(f"{self.duration_months} Month{'s' if self.duration_months > 1 else ''}")
        if self.duration_days:
            parts.append(f"{self.duration_days} Day{'s' if self.duration_days > 1 else ''}")
        return ", ".join(parts) if parts else "0 Days"

    def compute_end_date(self, start_date: date) -> date:
        """
        Computes exact expiry end date given a start date.
        Accurately handles calendar month additions, month-end dates,
        and leap-year cases.
        E.g.:
        - 01-01-2026 + 12 months -> 31-12-2026
        - 01-02-2024 (leap year) + 1 month -> 29-02-2024
        - 01-02-2025 (non-leap) + 1 month -> 28-02-2025
        - 31-01-2026 + 1 month -> 28-02-2026
        """
        if not start_date:
            start_date = timezone.now().date()

        if self.duration_months > 0:
            raw_target = start_date + relativedelta(months=self.duration_months, days=self.duration_days)
            # Standard membership period subtracts 1 day so 01-Jan to 31-Dec is 12 full months
            computed = raw_target - timedelta(days=1)
            # If start_date was on the last day of the month and raw_target was clamped to the last day of the target month
            # (e.g. 31-Jan -> clamped to 28-Feb), then the full month should include that last day:
            is_start_month_end = (start_date + timedelta(days=1)).day == 1
            if is_start_month_end and (raw_target.day == (raw_target + timedelta(days=1)).day - 1 or (raw_target + timedelta(days=1)).day == 1):
                computed = raw_target
            return computed
        elif self.duration_days > 0:
            return start_date + timedelta(days=self.duration_days - 1)
        else:
            return start_date

    def calculate_late_fee(self, as_of_date: date, end_date: date, grace_days: int = None) -> Decimal:
        """
        Calculates accrued late fee based on the plan's policy,
        end date, and grace period.
        """
        if self.late_fee_type == LateFeeType.NONE or self.late_fee_amount <= Decimal('0.00'):
            return Decimal('0.00')

        if grace_days is None:
            grace_days = self.grace_period_days

        grace_deadline = end_date + timedelta(days=grace_days)
        if as_of_date <= grace_deadline:
            return Decimal('0.00')

        if self.late_fee_type == LateFeeType.FLAT:
            return self.late_fee_amount
        elif self.late_fee_type == LateFeeType.PER_DAY:
            days_overdue = (as_of_date - grace_deadline).days
            return Decimal(days_overdue) * self.late_fee_amount

        return Decimal('0.00')


class DiscountConcession(models.Model):
    """
    Discount and concession categories (e.g. Retired Railway Employee, Senior Citizen, Festival Special).
    """
    name = models.CharField(max_length=120, unique=True)
    description = models.CharField(max_length=255, blank=True)
    discount_type = models.CharField(
        max_length=20,
        choices=DiscountType.choices,
        default=DiscountType.PERCENTAGE
    )
    discount_value = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Percentage (e.g. 50.00 for 50%) or flat amount in INR (₹)."
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Discount / Concession"
        verbose_name_plural = "Discounts & Concessions"
        ordering = ['name']

    def __str__(self):
        symbol = "%" if self.discount_type == DiscountType.PERCENTAGE else "₹"
        return f"{self.name} ({symbol}{self.discount_value:,.2f})"

    def calculate_discount_amount(self, base_fee: Decimal) -> Decimal:
        """Computes discount in INR capped between 0 and base_fee."""
        if base_fee <= Decimal('0.00') or not self.is_active:
            return Decimal('0.00')

        if self.discount_type == DiscountType.PERCENTAGE:
            discount = (base_fee * self.discount_value) / Decimal('100.00')
        else:
            discount = self.discount_value

        # Round to 2 decimal places and cap at base_fee
        discount = round(discount, 2)
        return min(max(discount, Decimal('0.00')), base_fee)


class MemberPlanAssignment(models.Model):
    """
    Association between a Member and an assigned Membership Plan.
    Stores immutable snapshot of base fee and applied discount at assignment time,
    preventing retrospective changes when plan fees are updated.
    """
    member = models.ForeignKey(
        'members.Member',
        on_delete=models.CASCADE,
        related_name='plan_assignments'
    )
    plan = models.ForeignKey(
        Plan,
        on_delete=models.PROTECT,
        related_name='assignments'
    )
    discount = models.ForeignKey(
        DiscountConcession,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='assignments'
    )
    start_date = models.DateField(default=timezone.now)
    end_date = models.DateField()
    grace_period_days = models.PositiveIntegerField(default=15)
    base_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Plan fee snapshot at assignment time (immutable)."
    )
    discount_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00')
    )
    final_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Net fee payable after discounts (base_fee - discount_amount)."
    )
    is_current = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Indicates the member's current active plan assignment."
    )
    assigned_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='assigned_member_plans'
    )
    assigned_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = "Member Plan Assignment"
        verbose_name_plural = "Member Plan Assignments"
        ordering = ['-start_date', '-id']
        indexes = [
            models.Index(fields=['member', 'is_current']),
            models.Index(fields=['end_date']),
        ]

    def __str__(self):
        return f"{self.member.name} - {self.plan.name} (Valid: {self.start_date:%d-%m-%Y} to {self.end_date:%d-%m-%Y})"

    def clean(self):
        super().clean()
        # Enforce that deactivated plans cannot be newly assigned
        if not self.pk and self.plan and not self.plan.is_active:
            raise ValidationError({'plan': f"Plan '{self.plan.name}' is deactivated and cannot be newly assigned."})

        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError({'end_date': "End date cannot be prior to start date."})

    def save(self, *args, **kwargs):
        # Auto-compute dates and fees if not explicitly set
        if not self.end_date and self.plan and self.start_date:
            self.end_date = self.plan.compute_end_date(self.start_date)

        if self.grace_period_days is None and self.plan:
            self.grace_period_days = self.plan.grace_period_days

        if self.base_fee is None and self.plan:
            self.base_fee = self.plan.fee

        if self.discount:
            self.discount_amount = self.discount.calculate_discount_amount(self.base_fee)
        else:
            self.discount_amount = Decimal('0.00')

        self.final_fee = max(self.base_fee - self.discount_amount, Decimal('0.00'))

        # When creating a new current assignment, set previous assignments for this member to not current
        with transaction.atomic():
            if self.is_current and self.member:
                MemberPlanAssignment.objects.filter(member=self.member, is_current=True).exclude(pk=self.pk).update(is_current=False)
            super().save(*args, **kwargs)

    @property
    def is_expired(self) -> bool:
        return timezone.now().date() > self.end_date

    @property
    def is_in_grace_period(self) -> bool:
        today = timezone.now().date()
        grace_end = self.end_date + timedelta(days=self.grace_period_days)
        return self.end_date < today <= grace_end

    @property
    def current_late_fee(self) -> Decimal:
        return self.plan.calculate_late_fee(
            as_of_date=timezone.now().date(),
            end_date=self.end_date,
            grace_days=self.grace_period_days
        )
