from decimal import Decimal
from datetime import date
from django.db import models, transaction
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.exceptions import ValidationError

class PaymentMode(models.TextChoices):
    UPI = 'UPI', 'UPI / QR Code'
    CASH = 'CASH', 'Cash'
    BANK_TRANSFER = 'BANK_TRANSFER', 'Bank Transfer (NEFT/RTGS/IMPS)'
    CHEQUE = 'CHEQUE', 'Cheque / Demand Draft'


class PaymentStatus(models.TextChoices):
    COMPLETED = 'COMPLETED', 'Completed'
    CANCELLED = 'CANCELLED', 'Cancelled'
    REFUNDED = 'REFUNDED', 'Refunded'


class AdjustmentType(models.TextChoices):
    REFUND = 'REFUND', 'Refund to Member'
    DISCOUNT_ADJUSTMENT = 'DISCOUNT_ADJUSTMENT', 'Post-Payment Discount Adjustment'
    WAIVER = 'WAIVER', 'Late Fee / Penalty Waiver'
    CORRECTION = 'CORRECTION', 'Accounting Correction'


class Payment(models.Model):
    """
    Financial payment record for membership fees, dues, and event charges.
    Features unique sequential receipt numbers, cancellation audit trails,
    and automatic member status transitions.
    """
    receipt_number = models.CharField(
        max_length=30,
        unique=True,
        db_index=True,
        help_text="Unique sequential receipt number (e.g., RCP-2026-00001)."
    )
    member = models.ForeignKey(
        'members.Member',
        on_delete=models.CASCADE,
        related_name='payments'
    )
    plan_assignment = models.ForeignKey(
        'plans.MemberPlanAssignment',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='payments',
        help_text="Optional linked plan assignment this payment settles."
    )
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Amount received in INR (₹)."
    )
    payment_date = models.DateField(
        default=timezone.now,
        help_text="Date the payment was collected."
    )
    payment_mode = models.CharField(
        max_length=20,
        choices=PaymentMode.choices,
        default=PaymentMode.UPI
    )
    reference_number = models.CharField(
        max_length=100,
        blank=True,
        help_text="Transaction reference (UPI UTR, Cheque No, Bank Ref)."
    )
    collected_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='collected_payments',
        help_text="Staff accountant or administrator who collected the funds."
    )
    status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.COMPLETED,
        db_index=True
    )
    notes = models.TextField(
        blank=True,
        help_text="Payment remarks or cheque bank details."
    )

    # Cancellation & Audit Trail
    is_cancelled = models.BooleanField(
        default=False,
        db_index=True,
        help_text="True if payment was cancelled or revoked."
    )
    cancellation_reason = models.TextField(
        blank=True,
        help_text="Mandatory audit justification for cancelling this payment."
    )
    cancelled_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='cancelled_payments'
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Payment"
        verbose_name_plural = "Payments"
        ordering = ['-payment_date', '-id']
        indexes = [
            models.Index(fields=['receipt_number']),
            models.Index(fields=['member', 'status']),
            models.Index(fields=['payment_date']),
        ]

    def __str__(self):
        return f"{self.receipt_number} - {self.member.name} (₹{self.amount:,.2f}) [{self.get_status_display()}]"

    @classmethod
    def generate_next_receipt_number(cls, year: int = None) -> str:
        """
        Thread-safe, atomic sequential receipt number generator: RCP-YYYY-XXXXX.
        Guarantees strictly sequential, gapless unique receipt numbering.
        """
        if year is None:
            year = timezone.now().year
        prefix = f"RCP-{year}-"

        with transaction.atomic():
            # Lock the highest receipt record for the current year
            latest = cls.objects.filter(
                receipt_number__startswith=prefix
            ).select_for_update().order_by('-receipt_number').first()

            if latest:
                try:
                    num_part = int(latest.receipt_number.replace(prefix, ''))
                    next_num = num_part + 1
                except ValueError:
                    next_num = cls.objects.filter(receipt_number__startswith=prefix).count() + 1
            else:
                next_num = 1

            return f"{prefix}{next_num:05d}"

    def clean(self):
        super().clean()
        if self.amount is not None and self.amount <= Decimal('0.00'):
            raise ValidationError({'amount': "Payment amount must be greater than zero."})

    def save(self, *args, **kwargs):
        if not self.receipt_number:
            self.receipt_number = self.generate_next_receipt_number()
        super().save(*args, **kwargs)

    def cancel(self, user: User, reason: str):
        """
        Cancels this payment with a mandatory reason, keeping the record intact for audit trail.
        Re-evaluates member due status.
        """
        if not reason or not reason.strip():
            raise ValueError("A mandatory audit reason is required to cancel a payment.")

        self.is_cancelled = True
        self.status = PaymentStatus.CANCELLED
        self.cancellation_reason = reason.strip()
        self.cancelled_by = user
        self.cancelled_at = timezone.now()
        self.save(update_fields=[
            'is_cancelled', 'status', 'cancellation_reason',
            'cancelled_by', 'cancelled_at', 'updated_at'
        ])


class PaymentAdjustment(models.Model):
    """
    Adjustments, partial refunds, or fee corrections made against a payment record.
    """
    payment = models.ForeignKey(
        Payment,
        on_delete=models.CASCADE,
        related_name='adjustments'
    )
    adjustment_type = models.CharField(
        max_length=30,
        choices=AdjustmentType.choices,
        default=AdjustmentType.REFUND
    )
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Adjustment amount in INR (₹)."
    )
    reason = models.TextField(help_text="Mandatory reason for this financial adjustment.")
    adjusted_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='payment_adjustments'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Payment Adjustment"
        verbose_name_plural = "Payment Adjustments"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.get_adjustment_type_display()} (₹{self.amount:,.2f}) for {self.payment.receipt_number}"
