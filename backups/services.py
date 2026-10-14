import os
import gzip
import io
import json
import hashlib
from datetime import timedelta
from typing import Optional, Dict, Any, List

from django.conf import settings
from django.core.management import call_command
from django.utils import timezone
from django.contrib.auth.models import User

from backups.models import BackupRecord, BackupType, BackupStatus


def ensure_backup_dir() -> str:
    """Ensures the backup storage directory exists and returns its absolute path."""
    backup_dir = getattr(settings, 'BACKUP_STORAGE_DIR', settings.BASE_DIR / 'backups_storage')
    os.makedirs(str(backup_dir), exist_ok=True)
    return str(backup_dir)


def create_database_backup(
    backup_type: str = BackupType.MANUAL,
    user: Optional[User] = None
) -> BackupRecord:
    """
    Creates a full database snapshot serialized to gzipped JSON,
    calculates cryptographic SHA-256 checksum, and stores audit metadata.
    """
    backup_dir = ensure_backup_dir()
    timestamp = timezone.now().strftime('%Y%m%d_%H%M%S')
    file_name = f"railclub_backup_{timestamp}.json.gz"
    file_path = os.path.join(backup_dir, file_name)

    # Initialize record
    record = BackupRecord.objects.create(
        backup_type=backup_type,
        file_name=file_name,
        file_path=file_path,
        created_by=user,
        status=BackupStatus.IN_PROGRESS
    )

    try:
        # Dump data into buffer
        buf = io.StringIO()
        call_command(
            'dumpdata',
            natural_foreign=True,
            natural_primary=True,
            exclude=['contenttypes', 'auth.Permission', 'sessions'],
            stdout=buf
        )
        data_str = buf.getvalue()

        # Count dumped objects
        try:
            parsed = json.loads(data_str)
            record_count = len(parsed) if isinstance(parsed, list) else 0
        except json.JSONDecodeError:
            record_count = 0

        # Gzip compress to file
        compressed_bytes = gzip.compress(data_str.encode('utf-8'))
        with open(file_path, 'wb') as f:
            f.write(compressed_bytes)

        # Compute SHA-256
        hasher = hashlib.sha256(compressed_bytes)
        checksum = hasher.hexdigest()
        file_size = len(compressed_bytes)

        # Update record
        record.file_size_bytes = file_size
        record.checksum = checksum
        record.total_records = record_count
        record.status = BackupStatus.SUCCESS
        record.completed_at = timezone.now()
        record.save(update_fields=[
            'file_size_bytes', 'checksum', 'total_records',
            'status', 'completed_at'
        ])

        # Enforce retention policy
        retention_days = getattr(settings, 'BACKUP_RETENTION_DAYS', 30)
        cleanup_old_backups(retention_days=retention_days)

        return record

    except Exception as e:
        record.status = BackupStatus.FAILED
        record.error_message = str(e)
        record.completed_at = timezone.now()
        record.save(update_fields=['status', 'error_message', 'completed_at'])
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError:
                pass
        raise e


def cleanup_old_backups(retention_days: int = 30) -> int:
    """
    Deletes backup files and records that exceed the retention window.
    Always preserves at least the 3 most recent backups.
    """
    cutoff = timezone.now() - timedelta(days=retention_days)
    old_records = BackupRecord.objects.filter(created_at__lt=cutoff).order_by('-created_at')

    # Retain at least 3 recent backups regardless of age
    total_count = BackupRecord.objects.count()
    if total_count <= 3:
        return 0

    deletable = old_records[3:] if total_count - old_records.count() < 3 else old_records

    deleted_count = 0
    for rec in deletable:
        if os.path.exists(rec.file_path):
            try:
                os.remove(rec.file_path)
            except OSError:
                pass
        rec.delete()
        deleted_count += 1

    return deleted_count
