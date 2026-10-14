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
