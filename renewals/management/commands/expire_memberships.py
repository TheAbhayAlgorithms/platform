from datetime import datetime
from django.core.management.base import BaseCommand
from django.utils import timezone
from renewals.services import process_auto_expiry


class Command(BaseCommand):
    help = "Batch sweep to identify memberships past their validity and grace periods and mark them EXPIRED."

    def add_arguments(self, parser):
        parser.add_argument(
            '--date',
            type=str,
            help="Simulate execution as of a specific date in YYYY-MM-DD format."
        )

    def handle(self, *args, **options):
        date_str = options.get('date')
        if date_str:
            try:
                as_of_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                self.stderr.write(self.style.ERROR(f"Invalid date format: {date_str}. Expected YYYY-MM-DD."))
                return
        else:
            as_of_date = timezone.now().date()

        self.stdout.write(f"Executing membership expiry sweep as of {as_of_date:%d-%m-%Y}...")
        results = process_auto_expiry(as_of_date=as_of_date)

        self.stdout.write(
            self.style.SUCCESS(
                f"Expiry sweep completed successfully:\n"
                f"  Total Active/Due Evaluated: {results['total_checked']}\n"
                f"  Valid & Active: {results['active_valid_count']}\n"
                f"  In Grace Period: {results['in_grace_count']}\n"
                f"  Transitioned to EXPIRED: {results['expired_count']}"
            )
        )
        if results['expired_member_ids']:
            self.stdout.write(f"  Expired Member IDs: {', '.join(results['expired_member_ids'][:20])}")
