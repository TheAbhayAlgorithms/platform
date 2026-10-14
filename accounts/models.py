import secrets
import hashlib
from datetime import timedelta
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.exceptions import ValidationError
from core.encryption import (
    EncryptedCharField,
    compute_blind_index,
    normalize_phone,
)

class RoleChoices(models.TextChoices):
    SUPER_ADMIN = 'SUPER_ADMIN', 'Super Admin'
    ACCOUNTANT = 'ACCOUNTANT', 'Accountant'
    EVENT_MANAGER = 'EVENT_MANAGER', 'Event Manager'
    VIEWER = 'VIEWER', 'Viewer'


class UserProfile(models.Model):
    """
    Extends Django User with Role-Based Access Control,
    encrypted phone, 2FA settings, and brute-force lockout tracking.
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(
        max_length=30,
        choices=RoleChoices.choices,
        default=RoleChoices.VIEWER,
        help_text="Role determining administrative permissions."
    )
    phone = EncryptedCharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Encrypted mobile phone number (AES-256 Fernet)."
    )
    phone_blind_index = models.CharField(
        max_length=64,
        db_index=True,
        blank=True,
        null=True,
        help_text="Keyed HMAC-SHA256 blind index for exact phone lookup."
    )
    is_2fa_enabled = models.BooleanField(
        default=True,
        help_text="Enforces 2-step OTP verification on admin login."
    )
    failed_login_attempts = models.PositiveIntegerField(
        default=0,
        help_text="Tracks consecutive failed login attempts."
    )
    locked_until = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Account locked timestamp (15 mins after 5 failed attempts)."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "User Profile"
        verbose_name_plural = "User Profiles"

    def __str__(self):
        return f"{self.user.username} ({self.get_role_display()})"

    def save(self, *args, **kwargs):
        if self.phone:
            try:
                # If plain phone passed, normalize and update blind index
                if not str(self.phone).startswith('gAAAAA'):
                    normalized = normalize_phone(self.phone)
                    self.phone = normalized
                    self.phone_blind_index = compute_blind_index(normalized)
            except ValidationError:
                pass
        super().save(*args, **kwargs)

    def is_locked_out(self) -> bool:
        """Returns True if user is currently locked out."""
        if self.locked_until and self.locked_until > timezone.now():
            return True
        return False

    def get_remaining_lockout_seconds(self) -> int:
        if self.is_locked_out():
            return int((self.locked_until - timezone.now()).total_seconds())
        return 0

    def record_failed_attempt(self):
        """Increments failed attempt count and applies 15-min lockout at 5 attempts."""
        self.failed_login_attempts += 1
        if self.failed_login_attempts >= 5:
            self.locked_until = timezone.now() + timedelta(minutes=15)
        self.save(update_fields=['failed_login_attempts', 'locked_until'])

    def reset_failed_attempts(self):
        """Resets failed count and clears lockout."""
        if self.failed_login_attempts > 0 or self.locked_until is not None:
            self.failed_login_attempts = 0
            self.locked_until = None
            self.save(update_fields=['failed_login_attempts', 'locked_until'])

    # Permission helper methods
    def has_role(self, *roles) -> bool:
        return self.role in roles

    @property
    def is_super_admin(self) -> bool:
        return self.role == RoleChoices.SUPER_ADMIN

    @property
    def is_accountant(self) -> bool:
        return self.role == RoleChoices.ACCOUNTANT

    @property
    def is_event_manager(self) -> bool:
        return self.role == RoleChoices.EVENT_MANAGER

    @property
    def is_viewer(self) -> bool:
        return self.role == RoleChoices.VIEWER

    def can_manage_users(self) -> bool:
        return self.is_super_admin

    def can_manage_payments(self) -> bool:
        return self.role in [RoleChoices.SUPER_ADMIN, RoleChoices.ACCOUNTANT]

    def can_manage_events(self) -> bool:
        return self.role in [RoleChoices.SUPER_ADMIN, RoleChoices.EVENT_MANAGER]

    def can_delete_records(self) -> bool:
        return self.is_super_admin


class AdminOTP(models.Model):
    """
    Stores cryptographically hashed, single-use, time-bound OTPs
    for two-step verification and password resets.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='admin_otps')
    otp_hash = models.CharField(max_length=64, help_text="SHA-256 hash of the 6-digit OTP.")
    purpose = models.CharField(max_length=32, default='login')
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    attempts = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Admin OTP"
        verbose_name_plural = "Admin OTPs"
        indexes = [
            models.Index(fields=['user', 'purpose', 'is_used']),
        ]

    def __str__(self):
        return f"OTP for {self.user.username} ({self.purpose})"

    @classmethod
    def hash_otp(cls, code: str) -> str:
        return hashlib.sha256(str(code).strip().encode('utf-8')).hexdigest()

    @classmethod
    def create_for_user(cls, user: User, purpose: str = 'login', validity_minutes: int = 5) -> str:
        """
        Invalidates any pending unused OTP for this user and creates a new one.
        Returns the plaintext 6-digit code for delivery (only hashed in DB).
        """
        cls.objects.filter(user=user, purpose=purpose, is_used=False).update(is_used=True)
        # Generate cryptographically secure 6-digit number
        raw_code = f"{secrets.randbelow(900000) + 100000:06d}"
        hashed = cls.hash_otp(raw_code)
        expires_at = timezone.now() + timedelta(minutes=validity_minutes)

        cls.objects.create(
            user=user,
            otp_hash=hashed,
            purpose=purpose,
            expires_at=expires_at,
            is_used=False,
            attempts=0,
        )
        return raw_code

    def verify(self, candidate_code: str) -> bool:
        """
        Validates OTP code against hash.
        Enforces:
        - Must not be already used
        - Must not be expired
        - Max 3 attempts allowed
        """
        if self.is_used:
            return False

        if timezone.now() > self.expires_at:
            return False

        if self.attempts >= 3:
            return False

        self.attempts += 1
        candidate_hash = self.hash_otp(candidate_code)

        if candidate_hash == self.otp_hash:
            self.is_used = True
            self.save(update_fields=['attempts', 'is_used'])
            return True
        else:
            self.save(update_fields=['attempts'])
            return False
