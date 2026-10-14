import os
from pathlib import Path
from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.core.paginator import Paginator
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404, HttpResponseForbidden
from django.views.decorators.http import require_POST
from django.db import models

from accounts.decorators import super_admin_required
from backups.models import BackupRecord, BackupType, BackupStatus
from backups.services import create_database_backup, ensure_backup_dir


@super_admin_required
def backup_dashboard(request):
    """
    Super Administrator security center for automated disaster recovery,
    archive logs, cryptographic SHA-256 audits, and manual snapshot triggers.
    """
    backups_qs = BackupRecord.objects.select_related('created_by').order_by('-created_at')

    all_backups = BackupRecord.objects.all()
    total_size = all_backups.filter(status=BackupStatus.SUCCESS).aggregate(total=models.Sum('file_size_bytes'))['total'] or 0
    last_successful = all_backups.filter(status=BackupStatus.SUCCESS).first()

    total_mb = f"{total_size / (1024 * 1024):.2f} MB" if total_size >= 1024 * 1024 else f"{total_size / 1024:.1f} KB"

    stats = {
        'total_count': all_backups.count(),
        'success_count': all_backups.filter(status=BackupStatus.SUCCESS).count(),
        'failed_count': all_backups.filter(status=BackupStatus.FAILED).count(),
        'total_storage': total_mb,
        'last_backup': last_successful,
        'retention_days': getattr(settings, 'BACKUP_RETENTION_DAYS', 30),
    }

    paginator = Paginator(backups_qs, 15)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'stats': stats,
    }
    return render(request, 'backups/dashboard.html', context)


@super_admin_required
@require_POST
def backup_trigger_manual(request):
    """Super Admin action to immediately generate a database backup snapshot."""
    try:
        record = create_database_backup(backup_type=BackupType.MANUAL, user=request.user)
        messages.success(
            request,
            f"Manual backup snapshot {record.backup_id} created successfully! "
            f"({record.file_size_display}, {record.total_records} records archived)."
        )
    except Exception as e:
        messages.error(request, f"Backup execution failed: {str(e)}")

    return redirect('backups:dashboard')


@super_admin_required
def backup_download(request, backup_id):
    """
    Secure download generator for compressed backup files.
    Enforces strict path containment within BACKUP_STORAGE_DIR to prevent directory traversal.
    """
    record = get_object_or_404(BackupRecord, pk=backup_id)

    if record.status != BackupStatus.SUCCESS:
        raise Http404("Cannot download an incomplete or failed backup archive.")

    backup_dir = Path(ensure_backup_dir()).resolve()
    target_file = Path(record.file_path).resolve()

    # Prevent path traversal attacks
    try:
        target_file.relative_to(backup_dir)
    except ValueError:
        raise PermissionDenied("Security violation: path traversal outside authorized backup storage.")

    if not target_file.is_file():
        raise Http404("The requested backup archive file does not exist on disk.")

    response = FileResponse(open(str(target_file), 'rb'), as_attachment=True, filename=record.file_name)
    return response


@super_admin_required
@require_POST
def backup_verify(request, backup_id):
    """Super Admin action to verify cryptographic SHA-256 checksum on disk."""
    record = get_object_or_404(BackupRecord, pk=backup_id)

    is_valid = record.verify_integrity()
    if is_valid:
        messages.success(
            request,
            f"Integrity verified for {record.backup_id}! "
            f"SHA-256 checksum ({record.checksum[:16]}...) matches file on disk."
        )
    else:
        messages.error(
            request,
            f"Integrity check FAILED for {record.backup_id}! "
            f"The file on disk is missing or has been altered."
        )

    return redirect('backups:dashboard')
