from datetime import date
from django.db import models, transaction
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.exceptions import ValidationError
from core.encryption import (
    EncryptedCharField,
    compute_blind_index,
    normalize_phone,
)

class MemberStatus(models.TextChoices):
    ACTIVE = 'ACTIVE', 'Active'
    DUE = 'DUE', 'Due'
    EXPIRED = 'EXPIRED', 'Expired'
    SUSPENDED = 'SUSPENDED', 'Suspended'
    REMOVED = 'REMOVED', 'Removed'


class DepartmentChoices(models.TextChoices):
    ENGINEERING = 'ENGINEERING', 'Civil Engineering'
    OPERATING = 'OPERATING', 'Operating / Traffic'
    COMMERCIAL = 'COMMERCIAL', 'Commercial'
    MECHANICAL = 'MECHANICAL', 'Mechanical Engineering'
    ELECTRICAL = 'ELECTRICAL', 'Electrical Engineering'
    SIGNAL_TELECOM = 'SIGNAL_TELECOM', 'Signal & Telecommunication (S&T)'
    PERSONNEL = 'PERSONNEL', 'Personnel / Administration'
    ACCOUNTS = 'ACCOUNTS', 'Accounts & Finance'
    MEDICAL = 'MEDICAL', 'Medical'
    SECURITY_RPF = 'SECURITY_RPF', 'Railway Protection Force (RPF)'
    STORES = 'STORES', 'Stores / Materials Management'
    OTHER = 'OTHER', 'Other / Railway Administration'


class MemberQuerySet(models.QuerySet):
    def active_records(self):
        """Returns non-removed members (excludes soft-deleted)."""
        return self.filter(is_removed=False)

    def search_query(self, term: str):
        """
        Search by name (case-insensitive substring) or by phone / employee_id
        using blind index lookup.
        """
        if not term:
            return self
        clean_term = term.strip()
        blind_idx = compute_blind_index(clean_term)

        # Also check if term can be normalized as an Indian phone number
        phone_blind_idx = None
        try:
            norm_phone = normalize_phone(clean_term)
            phone_blind_idx = compute_blind_index(norm_phone)
        except ValidationError:
            pass

        lookup = models.Q(name__icontains=clean_term) | models.Q(membership_id__iexact=clean_term)
        if phone_blind_idx:
            lookup |= models.Q(phone_blind_index=phone_blind_idx)
        lookup |= models.Q(phone_blind_index=blind_idx)
        lookup |= models.Q(employee_id_blind_index=blind_idx)

        return self.filter(lookup)


class Member(models.Model):
    """
    Railway Employee Institute Member record.
    Sensitive contact and employee ID fields are encrypted at rest with AES-256 Fernet,
    paired with keyed HMAC-SHA256 blind indexes for fast indexing and lookups.
    """
    membership_id = models.CharField(
        max_length=20,
        unique=True,
        db_index=True,
        help_text="Unique auto-generated membership identifier (e.g. RC-2026-00001)."
    )
    name = models.CharField(
        max_length=150,
        help_text="Full legal name of the railway employee."
    )
    phone = EncryptedCharField(
        max_length=255,
        help_text="Encrypted Indian mobile number (+91XXXXXXXXXX)."
    )
    phone_blind_index = models.CharField(
        max_length=64,
        db_index=True,
        help_text="Keyed HMAC-SHA256 blind index for exact phone lookup."
    )
    employee_id = EncryptedCharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Encrypted Railway Employee ID/PF Number."
    )
    employee_id_blind_index = models.CharField(
        max_length=64,
        db_index=True,
        blank=True,
        null=True,
        help_text="Keyed HMAC-SHA256 blind index for exact employee ID lookup."
    )
    department = models.CharField(
        max_length=60,
        choices=DepartmentChoices.choices,
        default=DepartmentChoices.ENGINEERING,
        help_text="Railway department."
    )
    address = models.TextField(
        blank=True,
        help_text="Residential or railway colony address."
    )
    date_joined = models.DateField(
        default=timezone.now,
        help_text="Date membership was initiated."
    )
    status = models.CharField(
        max_length=20,
        choices=MemberStatus.choices,
        default=MemberStatus.ACTIVE,
        db_index=True,
        help_text="Current membership standing."
    )
    whatsapp_opt_in = models.BooleanField(
        default=True,
        help_text="Consent for receiving WhatsApp automated alerts (DPDP compliance)."
    )
    notes = models.TextField(
        blank=True,
        help_text="Administrative notes or remarks."
    )

    # Soft Delete tracking
    is_removed = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Soft-delete flag preserving history and audit compliance."
    )
    removed_at = models.DateTimeField(null=True, blank=True)
    removed_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='removed_members'
    )
    removal_reason = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = MemberQuerySet.as_manager()

    class Meta:
        verbose_name = "Member"
        verbose_name_plural = "Members"
        ordering = ['-date_joined', '-id']
        indexes = [
            models.Index(fields=['phone_blind_index']),
            models.Index(fields=['employee_id_blind_index']),
            models.Index(fields=['status', 'is_removed']),
        ]

    def __str__(self):
        return f"{self.membership_id} - {self.name} ({self.get_status_display()})"

    @classmethod
    def generate_next_membership_id(cls, year: int = None) -> str:
        """
        Generates next unique sequential membership ID: RC-YYYY-XXXXX
        Thread-safe generation using transaction.
        """
        if year is None:
            year = timezone.now().year
        prefix = f"RC-{year}-"

        with transaction.atomic():
            latest = cls.objects.filter(membership_id__startswith=prefix).order_by('-membership_id').first()
            if latest:
                try:
                    num_part = int(latest.membership_id.replace(prefix, ''))
                    next_num = num_part + 1
                except ValueError:
                    next_num = cls.objects.filter(membership_id__startswith=prefix).count() + 1
            else:
                next_num = 1
            return f"{prefix}{next_num:05d}"

    def clean(self):
        super().clean()
        if self.phone:
            # If not already encrypted Fernet token
            if not str(self.phone).startswith('gAAAAA'):
                try:
                    normalized = normalize_phone(self.phone)
                    self.phone = normalized
                    blind_idx = compute_blind_index(normalized)
                    
                    # Duplicate check against other active members
                    duplicate = Member.objects.filter(phone_blind_index=blind_idx, is_removed=False)
                    if self.pk:
                        duplicate = duplicate.exclude(pk=self.pk)
                    if duplicate.exists():
                        raise ValidationError({'phone': f"A member with phone number {normalized} already exists ({duplicate.first().membership_id})."})
                except ValidationError as e:
                    raise e

    def save(self, *args, **kwargs):
        if not self.membership_id:
            self.membership_id = self.generate_next_membership_id()

        if self.phone and not str(self.phone).startswith('gAAAAA'):
            normalized = normalize_phone(self.phone)
            self.phone = normalized
            self.phone_blind_index = compute_blind_index(normalized)

        if self.employee_id and not str(self.employee_id).startswith('gAAAAA'):
            clean_emp = str(self.employee_id).strip()
            self.employee_id = clean_emp
            self.employee_id_blind_index = compute_blind_index(clean_emp)

        super().save(*args, **kwargs)

    def soft_delete(self, user: User, reason: str = ""):
        """Soft-deletes the member, retaining full historical audit records."""
        self.is_removed = True
        self.status = MemberStatus.REMOVED
        self.removed_at = timezone.now()
        self.removed_by = user
        self.removal_reason = reason
        self.save(update_fields=['is_removed', 'status', 'removed_at', 'removed_by', 'removal_reason', 'updated_at'])

    def restore(self, status: str = MemberStatus.ACTIVE):
        """Restores a soft-deleted member."""
        self.is_removed = False
        self.status = status
        self.removed_at = None
        self.removed_by = None
        self.removal_reason = ""
        self.save(update_fields=['is_removed', 'status', 'removed_at', 'removed_by', 'removal_reason', 'updated_at'])


class MemberFamily(models.Model):
    """
    Dependent family members (spouse, children, dependent parents)
    associated with an institute member.
    """
    RELATIONSHIP_CHOICES = [
        ('SPOUSE', 'Spouse'),
        ('SON', 'Son'),
        ('DAUGHTER', 'Daughter'),
        ('FATHER', 'Father'),
        ('MOTHER', 'Mother'),
        ('OTHER', 'Other Dependent'),
    ]

    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name='family_members')
    name = models.CharField(max_length=150)
    relationship = models.CharField(max_length=50, choices=RELATIONSHIP_CHOICES)
    date_of_birth = models.DateField(null=True, blank=True)
    phone = models.CharField(max_length=20, blank=True, help_text="Optional mobile number")
    notes = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Family Member"
        verbose_name_plural = "Family Members"
        ordering = ['relationship', 'name']

    def __str__(self):
        return f"{self.name} ({self.get_relationship_display()}) - {self.member.name}"
