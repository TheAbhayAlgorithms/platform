from django.db import models
from django.utils import timezone
from core.encryption import EncryptedCharField, compute_blind_index


class NotificationTemplate(models.TextChoices):
    PAYMENT_RECEIPT = 'PAYMENT_RECEIPT', 'Payment Receipt'
    RENEWAL_UPCOMING = 'RENEWAL_UPCOMING', 'Upcoming Renewal Reminder'
    PAYMENT_DUE = 'PAYMENT_DUE', 'Payment Due Reminder'
    MEMBERSHIP_EXPIRED = 'MEMBERSHIP_EXPIRED', 'Membership Expiry Notice'
    MEMBER_PORTAL_OTP = 'MEMBER_PORTAL_OTP', 'Portal Login OTP'
    CUSTOM = 'CUSTOM', 'Custom Notice'


class NotificationStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending'
    SENT = 'SENT', 'Sent'
    DELIVERED = 'DELIVERED', 'Delivered'
    READ = 'READ', 'Read'
    FAILED = 'FAILED', 'Failed'
    OPTED_OUT = 'OPTED_OUT', 'Opted Out (DPDP)'


class WhatsAppMessageLog(models.Model):
    """
    Audit log of all outbound WhatsApp communications dispatched by the platform.
    Features field encryption for recipient contact details, provider tracking,
    and Meta webhook lifecycle events (Sent -> Delivered -> Read).
    """
    member = models.ForeignKey(
        'members.Member',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='whatsapp_logs'
    )
    recipient_phone = EncryptedCharField(
        max_length=255,
        help_text="Encrypted recipient mobile number."
    )
    recipient_phone_blind_index = models.CharField(
        max_length=64,
        db_index=True,
        help_text="Keyed HMAC-SHA256 blind index for recipient lookup."
    )
    template_type = models.CharField(
        max_length=40,
        choices=NotificationTemplate.choices,
        default=NotificationTemplate.CUSTOM
    )
    message_body = models.TextField(
        help_text="Full rendered WhatsApp text message content."
    )
    sender_number = models.CharField(
        max_length=20,
        default='7039145304',
        help_text="Official Institute WhatsApp business phone number."
    )
    provider = models.CharField(
        max_length=30,
        default='mock',
        help_text="Underlying provider engine ('mock' or 'cloud_api')."
    )
    status = models.CharField(
        max_length=20,
        choices=NotificationStatus.choices,
        default=NotificationStatus.PENDING,
        db_index=True
    )
    external_message_id = models.CharField(
        max_length=120,
        blank=True,
        db_index=True,
        help_text="External Meta WhatsApp Message ID (WAMID)."
    )
    error_message = models.TextField(
        blank=True,
        help_text="Provider error diagnostics if delivery failed."
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "WhatsApp Message Log"
        verbose_name_plural = "WhatsApp Message Logs"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['member', '-created_at']),
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['external_message_id']),
        ]

    def __str__(self):
        target = self.member.name if self.member else "Unknown"
        return f"[{self.get_status_display()}] {self.get_template_type_display()} to {target} ({self.created_at:%d-%m-%Y %H:%M})"


class ReminderMilestone(models.TextChoices):
    RENEWAL_30D = 'RENEWAL_30D', 'Renewal 30 Days Before'
    RENEWAL_15D = 'RENEWAL_15D', 'Renewal 15 Days Before'
    RENEWAL_7D = 'RENEWAL_7D', 'Renewal 7 Days Before'
    RENEWAL_1D = 'RENEWAL_1D', 'Renewal 1 Day Before'
    GRACE_PERIOD = 'GRACE_PERIOD', 'In Grace Period Notice'
    EXPIRED = 'EXPIRED', 'Expired / Overdue Notice'
    PAYMENT_DUE = 'PAYMENT_DUE', 'Periodic Outstanding Balance Due'


class ScheduledReminderRecord(models.Model):
    """
    Audit log of automated milestone reminders dispatched by background jobs.
    Enforces de-duplication so members are never spammed twice for the same cycle milestone.
    """
    member = models.ForeignKey(
        'members.Member',
        on_delete=models.CASCADE,
        related_name='scheduled_reminder_records'
    )
    plan_assignment = models.ForeignKey(
        'plans.MemberPlanAssignment',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='reminder_records'
    )
    milestone = models.CharField(
        max_length=30,
        choices=ReminderMilestone.choices,
        db_index=True
    )
    dispatched_date = models.DateField(default=timezone.now, db_index=True)
    message_log = models.ForeignKey(
        WhatsAppMessageLog,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='reminder_record'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Scheduled Reminder Record"
        verbose_name_plural = "Scheduled Reminder Records"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['member', 'milestone']),
            models.Index(fields=['plan_assignment', 'milestone']),
            models.Index(fields=['dispatched_date']),
        ]

    def __str__(self):
        return f"{self.member.name} - {self.get_milestone_display()} ({self.dispatched_date:%d-%m-%Y})"

