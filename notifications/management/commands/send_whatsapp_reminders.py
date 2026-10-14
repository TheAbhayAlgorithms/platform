import datetime
from django.core.management.base import BaseCommand, CommandError
from notifications.reminders import run_automated_whatsapp_reminders


class Command(BaseCommand):
    help = "Dispatches automated WhatsApp reminders for renewals, grace period, expiry, and dues."

    def add_arguments(self, parser):
        parser.add_argument(
            '--date',
            type=str,
            help="Evaluate reminders as of specific date in YYYY-MM-DD format (defaults to today)."
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help="Simulate reminder evaluation without dispatching messages or writing records."
        )

    def handle(self, *args, **options):
        as_of_date = None
        date_str = options.get('date')
        if date_str:
            try:
                as_of_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                raise CommandError(f"Invalid date format '{date_str}'. Expected YYYY-MM-DD.")

        dry_run = options.get('dry_run', False)

        mode_str = "[DRY-RUN SIMULATION] " if dry_run else ""
        self.stdout.write(self.style.NOTICE(f"{mode_str}Evaluating automated WhatsApp reminders..."))

        stats = run_automated_whatsapp_reminders(as_of_date=as_of_date, dry_run=dry_run)

        self.stdout.write(self.style.SUCCESS(
            f"Sweep Completed for {stats['as_of_date']}:\n"
            f"  - Evaluated Members: {stats['evaluated_members']}\n"
            f"  - Renewal Reminders (30d/15d/7d/1d): {stats['renewal_reminders_sent']}\n"
            f"  - In-Grace Reminders: {stats['grace_reminders_sent']}\n"
            f"  - Expired Notices: {stats['expired_reminders_sent']}\n"
            f"  - Payment Due Notices: {stats['due_reminders_sent']}\n"
            f"  - Total Dispatched: {stats['total_dispatched']}\n"
            f"  - Skipped (DPDP Opt-Out): {stats['skipped_optout']}\n"
            f"  - Skipped (De-duplicated): {stats['skipped_dedup']}"
        ))
