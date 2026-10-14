import os
import hashlib
from django.db import models, transaction
from django.contrib.auth.models import User
from django.utils import timezone


class BackupType(models.TextChoices):
    AUTOMATED = 'AUTOMATED', 'Scheduled Automated Backup'
    MANUAL = 'MANUAL', 'On-Demand Administrator Backup'


class BackupStatus(models.TextChoices):
    IN_PROGRESS = 'IN_PROGRESS', 'In Progress'
    SUCCESS = 'SUCCESS', 'Completed & Verified'
    FAILED = 'FAILED', 'Failed'


class BackupRecord(models.Model):
    """
    Audit log of all database archives, compressed snapshots,
    SHA-256 tamper-evident integrity checksums, and retention lifecycle.
    """
    backup_id = models.CharField(
        max_length=25,
        unique=True,
        db_index=True,
        help_text="Sequential backup reference (e.g. BKP-2026-00001)."
    )
    backup_type = models.CharField(
        max_length=20,
        choices=BackupType.choices,
        default=BackupType.AUTOMATED,
        db_index=True
    )
    file_name = models.CharField(
        max_length=255,
        help_text="Name of the compressed backup archive file."
    )
    file_path = models.CharField(
        max_length=500,
        help_text="Absolute local filesystem storage path."
    )
    file_size_bytes = models.BigIntegerField(
        default=0,
        help_text="Archive file size in bytes."
    )
    checksum = models.CharField(
        max_length=64,
        blank=True,
        help_text="SHA-256 tamper-evident cryptographic checksum."
    )
    status = models.CharField(
        max_length=20,
        choices=BackupStatus.choices,
        default=BackupStatus.IN_PROGRESS,
        db_index=True
    )
    total_records = models.PositiveIntegerField(
        default=0,
        help_text="Count of database records captured in this snapshot."
    )
    error_message = models.TextField(
        blank=True,
        help_text="Diagnostic failure details if backup could not complete."
    )
    created_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='initiated_backups',
        help_text="User who initiated manual backup (null for scheduled automated tasks)."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Database Backup Record"
        verbose_name_plural = "Database Backup Records"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.backup_id} - {self.file_name} [{self.get_status_display()}]"

    @classmethod
    def generate_next_backup_id(cls, year: int = None) -> str:
        """
        Thread-safe generation of next sequential backup identifier: BKP-YYYY-NNNNN.
        """
        if year is None:
            year = timezone.now().year

        prefix = f"BKP-{year}-"
        with transaction.atomic():
            latest = cls.objects.select_for_update().filter(
                backup_id__startswith=prefix
            ).order_by('-backup_id').first()

            if latest:
                try:
                    num_part = int(latest.backup_id.split('-')[-1])
                    next_num = num_part + 1
                except (ValueError, IndexError):
                    next_num = 1
            else:
                next_num = 1

            return f"{prefix}{next_num:05d}"

    def save(self, *args, **kwargs):
        if not self.backup_id:
            self.backup_id = self.generate_next_backup_id()
        super().save(*args, **kwargs)

    @property
    def file_size_display(self) -> str:
        """Returns human readable file size format."""
        size = self.file_size_bytes
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        else:
            return f"{size / (1024 * 1024):.2f} MB"

    def verify_integrity(self) -> bool:
        """
        Computes the current SHA-256 hash of the archive file on disk
        and checks against recorded checksum.
        """
        if not os.path.exists(self.file_path):
            return False

        hasher = hashlib.sha256()
        try:
            with open(self.file_path, 'rb') as f:
                while chunk := f.read(65536):
                    hasher.update(chunk)
            computed_hash = hasher.hexdigest()
            return computed_hash == self.checksum
        except IOError:
            return False
