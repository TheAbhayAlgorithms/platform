import os
import gzip
import json
import hashlib
from datetime import timedelta
import pytest

from django.test import Client
from django.urls import reverse
from django.utils import timezone
from django.conf import settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.exceptions import PermissionDenied
from django.http import Http404

from accounts.models import UserProfile, RoleChoices
from backups.models import BackupRecord, BackupType, BackupStatus
from backups.services import (
    create_database_backup,
    cleanup_old_backups,
    ensure_backup_dir,
)


@pytest.fixture
def superadmin_user(db):
    user = User.objects.create_user(username="superadmin_user", password="password123")
    UserProfile.objects.create(user=user, role=RoleChoices.SUPER_ADMIN)
    return user


@pytest.fixture
def accountant_user(db):
    user = User.objects.create_user(username="acct_user", password="password123")
    UserProfile.objects.create(user=user, role=RoleChoices.ACCOUNTANT)
    return user


@pytest.fixture
def event_manager_user(db):
    user = User.objects.create_user(username="event_mgr_user", password="password123")
    UserProfile.objects.create(user=user, role=RoleChoices.EVENT_MANAGER)
    return user


@pytest.fixture
def viewer_user(db):
    user = User.objects.create_user(username="view_user", password="password123")
    UserProfile.objects.create(user=user, role=RoleChoices.VIEWER)
    return user


# =========================================================================
# 1. BACKUP ENGINE & CRYPTOGRAPHIC CHECKSUM TESTS
# =========================================================================

@pytest.mark.django_db
def test_create_database_backup_and_verify_integrity(superadmin_user):
    record = create_database_backup(backup_type=BackupType.MANUAL, user=superadmin_user)

    assert record.status == BackupStatus.SUCCESS
    assert record.backup_type == BackupType.MANUAL
    assert record.created_by == superadmin_user
    assert record.file_name.endswith('.json.gz')
    assert record.file_size_bytes > 0
    assert len(record.checksum) == 64
    assert os.path.exists(record.file_path)

    # Decompress and verify valid JSON
    with gzip.open(record.file_path, 'rt', encoding='utf-8') as f:
        data = json.load(f)
        assert isinstance(data, list)
        assert len(data) == record.total_records

    # Integrity verification
    assert record.verify_integrity() is True

    # Tampering test: modify the file bytes
    with open(record.file_path, 'ab') as f:
        f.write(b"corrupt_bytes")

    assert record.verify_integrity() is False

    # Cleanup
    if os.path.exists(record.file_path):
        os.remove(record.file_path)


@pytest.mark.django_db
def test_sequential_backup_id_generation():
    b1 = BackupRecord.objects.create(file_name="b1.json.gz", file_path="/tmp/b1.json.gz")
    b2 = BackupRecord.objects.create(file_name="b2.json.gz", file_path="/tmp/b2.json.gz")

    year = timezone.now().year
    assert b1.backup_id == f"BKP-{year}-00001"
    assert b2.backup_id == f"BKP-{year}-00002"


@pytest.mark.django_db
def test_backup_file_size_display():
    b_small = BackupRecord(file_size_bytes=500)
    assert b_small.file_size_display == "500 B"

    b_kb = BackupRecord(file_size_bytes=2048)
    assert "KB" in b_kb.file_size_display

    b_mb = BackupRecord(file_size_bytes=3 * 1024 * 1024)
    assert "MB" in b_mb.file_size_display


# =========================================================================
# 2. RETENTION POLICY & CLEANUP TESTS
# =========================================================================

@pytest.mark.django_db
def test_cleanup_old_backups_retention():
    backup_dir = ensure_backup_dir()
    past_date = timezone.now() - timedelta(days=45)

    # Create 4 old dummy backups and dummy files
    records = []
    for i in range(4):
        file_name = f"dummy_old_{i}.json.gz"
        file_path = os.path.join(backup_dir, file_name)
        with open(file_path, 'wb') as f:
            f.write(b"data")
        rec = BackupRecord.objects.create(file_name=file_name, file_path=file_path)
        # Manually update created_at via QuerySet to bypass auto_now_add
        BackupRecord.objects.filter(pk=rec.pk).update(created_at=past_date)
        records.append(rec)

    # Calling cleanup: should retain 3 and delete 1
    deleted = cleanup_old_backups(retention_days=30)
    assert deleted == 1
    assert BackupRecord.objects.count() == 3

    # Cleanup remaining dummy files
    for rec in BackupRecord.objects.all():
        if os.path.exists(rec.file_path):
            os.remove(rec.file_path)


# =========================================================================
# 3. MANAGEMENT COMMAND TEST
# =========================================================================

@pytest.mark.django_db
def test_run_automated_backup_management_command():
    call_command('run_automated_backup')
    latest = BackupRecord.objects.filter(backup_type=BackupType.AUTOMATED).order_by('-created_at').first()
    assert latest is not None
    assert latest.status == BackupStatus.SUCCESS
    assert os.path.exists(latest.file_path)

    # Cleanup
    if os.path.exists(latest.file_path):
        os.remove(latest.file_path)


# =========================================================================
# 4. PATH TRAVERSAL DEFENSE TEST
# =========================================================================

@pytest.mark.django_db
def test_backup_download_path_traversal_protection(client, superadmin_user):
    client.force_login(superadmin_user)

    # Create a malicious record attempting to escape backup dir
    malicious = BackupRecord.objects.create(
        file_name="traversal_test.json.gz",
        file_path="/etc/passwd",
        status=BackupStatus.SUCCESS
    )

    url = reverse('backups:download', kwargs={'backup_id': malicious.id})
    resp = client.get(url)
    assert resp.status_code == 403


# =========================================================================
# 5. STAFF VIEWS & RBAC PERMISSION TESTS
# =========================================================================

@pytest.mark.django_db
def test_backup_dashboard_access_rbac(superadmin_user, accountant_user, event_manager_user, viewer_user):
    client = Client()
    url = reverse('backups:dashboard')

    # Unauthenticated redirect
    assert client.get(url).status_code == 302

    # Non-superadmin roles forbidden (403)
    client.force_login(viewer_user)
    assert client.get(url).status_code == 403

    client.force_login(event_manager_user)
    assert client.get(url).status_code == 403

    client.force_login(accountant_user)
    assert client.get(url).status_code == 403

    # Super Admin allowed
    client.force_login(superadmin_user)
    resp = client.get(url)
    assert resp.status_code == 200
    assert "Automated Backups &amp; Disaster Recovery" in resp.content.decode()


@pytest.mark.django_db
def test_backup_trigger_and_verify_views(client, superadmin_user):
    client.force_login(superadmin_user)

    # Trigger manual backup
    trigger_url = reverse('backups:trigger')
    resp = client.post(trigger_url)
    assert resp.status_code == 302

    record = BackupRecord.objects.latest('created_at')
    assert record.status == BackupStatus.SUCCESS

    # Verify action
    verify_url = reverse('backups:verify', kwargs={'backup_id': record.id})
    resp = client.post(verify_url)
    assert resp.status_code == 302

    # Download action
    download_url = reverse('backups:download', kwargs={'backup_id': record.id})
    resp = client.get(download_url)
    assert resp.status_code == 200
    assert resp['Content-Type'] == 'application/gzip'

    # Cleanup
    if os.path.exists(record.file_path):
        os.remove(record.file_path)
