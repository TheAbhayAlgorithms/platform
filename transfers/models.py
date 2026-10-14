from django.db import models, transaction
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.exceptions import ValidationError


class Branch(models.Model):
    """
    Railway Club / Institute Division or Branch.
    """
    name = models.CharField(max_length=150, help_text="Institute or Club Branch Name")
    code = models.CharField(max_length=30, unique=True, db_index=True, help_text="Unique Division/Branch Code (e.g., NR-DLI)")
    zone = models.CharField(max_length=100, help_text="Railway Zone (e.g. Northern Railway, Western Railway)")
    division = models.CharField(max_length=100, help_text="Railway Division (e.g. Delhi, Mumbai, Danapur)")
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    contact_person = models.CharField(max_length=120, blank=True, help_text="Designation or Contact Person")
    contact_phone = models.CharField(max_length=30, blank=True)
    contact_email = models.EmailField(blank=True)
    is_home_branch = models.BooleanField(
        default=False,
        help_text="Designates the current home institute managing this installation."
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_home_branch', 'name']
        verbose_name = "Railway Branch / Division"
        verbose_name_plural = "Railway Branches & Divisions"

    def __str__(self):
        home_tag = " (Home Branch)" if self.is_home_branch else ""
        return f"{self.name} [{self.code}]{home_tag}"

    def clean(self):
        super().clean()
        if self.is_home_branch:
            # Ensure only one home branch exists
            existing_home = Branch.objects.filter(is_home_branch=True).exclude(pk=self.pk)
            if existing_home.exists():
                raise ValidationError({"is_home_branch": "Another branch is already designated as the Home Branch."})


class TransferType(models.TextChoices):
    OUTGOING = 'OUTGOING', 'Outgoing (Relieving / Transferring Out)'
    INCOMING = 'INCOMING', 'Incoming (Joining from another Division)'


class TransferStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending Clearance & Approval'
    APPROVED = 'APPROVED', 'Approved (NOC Issued)'
    REJECTED = 'REJECTED', 'Rejected'
    COMPLETED = 'COMPLETED', 'Transfer Finalized'
    CANCELLED = 'CANCELLED', 'Cancelled'


class InterDivisionalTransfer(models.Model):
    """
    Formal record of railway employee inter-divisional club transfer,
    including dues clearance audit, official office order tracking,
    and digital No Objection Certificate (NOC) generation.
    """
    transfer_id = models.CharField(
        max_length=30,
        unique=True,
        db_index=True,
        editable=False,
        help_text="Auto-generated identifier formatted as TRF-YYYY-NNNNN."
    )
    member = models.ForeignKey(
        'members.Member',
        on_delete=models.CASCADE,
        related_name='transfers',
        help_text="Member subject to inter-divisional transfer."
    )
    from_branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        related_name='transfers_out',
        help_text="Origin branch / institute."
    )
    to_branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        related_name='transfers_in',
        help_text="Destination branch / institute."
    )
    transfer_type = models.CharField(
        max_length=20,
        choices=TransferType.choices,
        default=TransferType.OUTGOING
    )
    transfer_order_number = models.CharField(
        max_length=100,
        help_text="Official Railway Competent Authority Office Order Number."
    )
    transfer_order_date = models.DateField(
        help_text="Date on which the official railway transfer order was issued."
    )
    effective_date = models.DateField(
        help_text="Relieving / joining effective date."
    )
    status = models.CharField(
        max_length=20,
        choices=TransferStatus.choices,
        default=TransferStatus.PENDING,
        db_index=True
    )
    dues_cleared = models.BooleanField(
        default=False,
        help_text="Flag indicating whether all subscription dues, loans, and hall bookings are settled."
    )
    dues_remarks = models.TextField(
        blank=True,
        help_text="Dues audit findings and verification notes."
    )
    noc_number = models.CharField(
        max_length=30,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        help_text="Digital No Objection Certificate number: NOC-YYYY-NNNNN."
    )
    noc_issued_at = models.DateTimeField(null=True, blank=True)
    remarks = models.TextField(
        blank=True,
        help_text="Reason for transfer, remarks, or transfer references."
    )
    rejection_reason = models.TextField(
        blank=True,
        help_text="Reason for rejecting the transfer request."
    )
    requested_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transfers_requested'
    )
    actioned_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transfers_actioned'
    )
    actioned_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Inter-Divisional Transfer"
        verbose_name_plural = "Inter-Divisional Transfers"

    def __str__(self):
        return f"{self.transfer_id} - {self.member.name} ({self.from_branch.code} -> {self.to_branch.code})"

    def clean(self):
        super().clean()
        if self.from_branch_id and self.to_branch_id and self.from_branch_id == self.to_branch_id:
            raise ValidationError("Origin branch and Destination branch cannot be the same.")

    @classmethod
    def generate_next_transfer_id(cls, year: int = None) -> str:
        """
        Generates thread-safe sequential ID formatted as TRF-YYYY-NNNNN.
        """
        if year is None:
            year = timezone.now().year

        prefix = f"TRF-{year}-"
        with transaction.atomic():
            last_record = cls.objects.select_for_update().filter(
                transfer_id__startswith=prefix
            ).order_by('-transfer_id').first()

            if last_record and last_record.transfer_id:
                try:
                    last_num = int(last_record.transfer_id.split('-')[-1])
                    next_num = last_num + 1
                except (ValueError, IndexError):
                    next_num = 1
            else:
                next_num = 1

            return f"{prefix}{next_num:05d}"

    @classmethod
    def generate_next_noc_number(cls, year: int = None) -> str:
        """
        Generates thread-safe sequential NOC number formatted as NOC-YYYY-NNNNN.
        """
        if year is None:
            year = timezone.now().year

        prefix = f"NOC-{year}-"
        with transaction.atomic():
            last_record = cls.objects.select_for_update().filter(
                noc_number__startswith=prefix
            ).order_by('-noc_number').first()

            if last_record and last_record.noc_number:
                try:
                    last_num = int(last_record.noc_number.split('-')[-1])
                    next_num = last_num + 1
                except (ValueError, IndexError):
                    next_num = 1
            else:
                next_num = 1

            return f"{prefix}{next_num:05d}"

    def save(self, *args, **kwargs):
        if not self.transfer_id:
            self.transfer_id = self.generate_next_transfer_id()
        super().save(*args, **kwargs)
