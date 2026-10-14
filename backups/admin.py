from django.contrib import admin
from backups.models import BackupRecord


@admin.register(BackupRecord)
class BackupRecordAdmin(admin.ModelAdmin):
    list_display = ('backup_id', 'backup_type', 'file_name', 'file_size_display', 'total_records', 'status', 'created_at')
    list_filter = ('backup_type', 'status', 'created_at')
    search_fields = ('backup_id', 'file_name', 'checksum')
    readonly_fields = ('backup_id', 'file_name', 'file_path', 'file_size_bytes', 'checksum', 'total_records', 'created_at', 'completed_at')
