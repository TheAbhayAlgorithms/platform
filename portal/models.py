import hashlib
import secrets
from datetime import timedelta
from django.db import models
from django.utils import timezone
from members.models import Member


class MemberOTP(models.Model):
    """
    Cryptographically hashed, single-use, time-bound OTP
    for member self-service portal verification.
    """
    member = models.ForeignKey(
        Member,
        on_delete=models.CASCADE,
        related_name='portal_otps'
    )
    phone_blind_index = models.CharField(
        max_length=64,
        db_index=True,
        help_text="Keyed HMAC-SHA256 blind index of the phone number used."
    )
    otp_hash = models.CharField(
        max_length=64,
        help_text="SHA-256 hash of the 6-digit OTP."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    attempts = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Member Portal OTP"
        verbose_name_plural = "Member Portal OTPs"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['member', 'is_used']),
            models.Index(fields=['phone_blind_index', '-created_at']),
        ]

    def __str__(self):
        return f"Portal OTP for {self.member.name} ({self.member.membership_id})"

    @classmethod
    def hash_otp(cls, code: str) -> str:
        return hashlib.sha256(str(code).strip().encode('utf-8')).hexdigest()

    @classmethod
    def create_for_member(cls, member: Member, validity_minutes: int = 5) -> str:
        """
        Invalidates any pending unused OTP for this member and generates a new one.
        Returns the plaintext 6-digit code for delivery (stored hashed in DB).
        """
        cls.objects.filter(member=member, is_used=False).update(is_used=True)
        raw_code = f"{secrets.randbelow(900000) + 100000:06d}"
        hashed = cls.hash_otp(raw_code)
        expires_at = timezone.now() + timedelta(minutes=validity_minutes)

        cls.objects.create(
            member=member,
            phone_blind_index=member.phone_blind_index,
            otp_hash=hashed,
            expires_at=expires_at,
            is_used=False,
            attempts=0
        )
        return raw_code

    def verify(self, candidate_code: str) -> bool:
        """
        Validates the candidate OTP.
        Enforces single-use, expiry, and max 3 attempts.
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
