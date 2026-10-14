from django.core.management.base import BaseCommand
from django.core.management import call_command


class Command(BaseCommand):
    help = "Master system bootstrap and verification orchestrator for RailClub Connect."

    def handle(self, *args, **options):
        self.stdout.write("=======================================================")
        self.stdout.write("     RAILCLUB CONNECT - MASTER SYSTEM BOOTSTRAP        ")
        self.stdout.write("=======================================================\n")

        self.stdout.write("--> Step 1: Applying Database Migrations...")
        call_command('migrate', interactive=False)
        self.stdout.write(self.style.SUCCESS("[OK] Database migrations completed.\n"))

        self.stdout.write("--> Step 2: Seeding Indian Railways Divisions & Branches...")
        call_command('seed_branches')
        self.stdout.write(self.style.SUCCESS("[OK] Railway divisions seeded.\n"))

        self.stdout.write("--> Step 3: Seeding Demonstration Staff, Plans, and Members...")
        call_command('seed_phase1_data')
        self.stdout.write(self.style.SUCCESS("[OK] Baseline platform demonstration data seeded.\n"))

        self.stdout.write("--> Step 4: Running Security & Cryptographic Audit...")
        call_command('security_audit')
        self.stdout.write(self.style.SUCCESS("[OK] Security audit completed.\n"))

        self.stdout.write("=======================================================")
        self.stdout.write("             SYSTEM READY FOR PRODUCTION / DEMO        ")
        self.stdout.write("=======================================================")
        self.stdout.write("Demonstration Credentials:")
        self.stdout.write("  - Super Admin:   admin@railclub.in     / Admin@123")
        self.stdout.write("  - Accountant:    accountant@railclub.in / Acct@123")
        self.stdout.write("  - Event Manager: events@railclub.in     / Events@123")
        self.stdout.write("  - Read-Only:     viewer@railclub.in     / Viewer@123")
        self.stdout.write("  - Member Portal: Enter registered mobile (e.g. +91 98111 22233)")
        self.stdout.write("=======================================================\n")
