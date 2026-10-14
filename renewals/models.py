from decimal import Decimal
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class RenewalRecord(models.Model):
    """
    Audit log of renewal transactions and plan rollover cycles.
    Tracks previous validity period, new validity period, plan,
    fees, and the staff user who initiated the renewal.
    """
    member = models.ForeignKey(
        'members.Member',
        on_delete=models.CASCADE,
        related_name='renewal_records'
    )
    previous_assignment = models.ForeignKey(
        'plans.MemberPlanAssignment',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='renewals_from'
    )
    new_assignment = models.ForeignKey(
        'plans.MemberPlanAssignment',
        on_delete=models.CASCADE,
        related_name='renewals_to'
    )
    plan = models.ForeignKey(
        'plans.Plan',
        on_delete=models.PROTECT,
        related_name='renewal_records'
    )
    renewed_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='renewals_initiated'
    )
    renewal_date = models.DateTimeField(auto_now_add=True, db_index=True)
    previous_end_date = models.DateField(null=True, blank=True)
    new_start_date = models.DateField()
    new_end_date = models.DateField()
    fee_charged = models.DecimalField(max_digits=10, decimal_places=2)
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = "Renewal Record"
        verbose_name_plural = "Renewal Records"
        ordering = ['-renewal_date']
        indexes = [
            models.Index(fields=['member', '-renewal_date']),
            models.Index(fields=['new_start_date']),
        ]

    def __str__(self):
        return (
            f"Renewal for {self.member.name} ({self.member.membership_id}) - "
            f"{self.plan.name} ({self.new_start_date:%d-%m-%Y} to {self.new_end_date:%d-%m-%Y})"
        )
