from django.core.management.base import BaseCommand
from backups.models import BackupType, BackupStatus
from backups.services import create_database_backup


class Command(BaseCommand):
    help = "Executes scheduled automated database snapshot and applies retention policy."

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Initiating scheduled automated database backup..."))
        try:
            record = create_database_backup(backup_type=BackupType.AUTOMATED)
            self.stdout.write(self.style.SUCCESS(
                f"Successfully completed backup {record.backup_id}!\n"
                f"File: {record.file_name} ({record.file_size_display})\n"
                f"Records: {record.total_records}\n"
                f"SHA-256: {record.checksum}"
            ))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Backup failed: {str(e)}"))
            raise e
