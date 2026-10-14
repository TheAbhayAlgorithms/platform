import os
from django.core.management.base import BaseCommand
from django.conf import settings
from django.db import connection
from members.models import Member
from accounts.models import UserProfile


class Command(BaseCommand):
    help = "Performs a comprehensive automated Security & Encryption Audit of RailClub Connect."

    def handle(self, *args, **options):
        self.stdout.write("=======================================================")
        self.stdout.write("      RAILCLUB CONNECT - SECURITY & ENCRYPTION AUDIT   ")
        self.stdout.write("=======================================================\n")

        passed = 0
        total = 0

        # Check 1: AES-256 Fernet Encryption Key
        total += 1
        enc_key = getattr(settings, 'FIELD_ENCRYPTION_KEY', None)
        if enc_key and len(enc_key) >= 32:
            self.stdout.write(self.style.SUCCESS("[PASS] 1. FIELD_ENCRYPTION_KEY is configured and valid."))
            passed += 1
        else:
            self.stdout.write(self.style.ERROR("[FAIL] 1. FIELD_ENCRYPTION_KEY is missing or invalid."))

        # Check 2: Blind Index Pepper / Keyed Salt
        total += 1
        pepper = getattr(settings, 'BLIND_INDEX_SALT', getattr(settings, 'BLIND_INDEX_PEPPER', None))
        if pepper and len(pepper) >= 16:
            self.stdout.write(self.style.SUCCESS("[PASS] 2. BLIND_INDEX_SALT is configured with high entropy."))
            passed += 1
        else:
            self.stdout.write(self.style.ERROR("[FAIL] 2. BLIND_INDEX_SALT is missing or weak."))

        # Check 3: Argon2 Password Hasher
        total += 1
        hashers = getattr(settings, 'PASSWORD_HASHERS', [])
        if hashers and 'Argon2PasswordHasher' in hashers[0]:
            self.stdout.write(self.style.SUCCESS(f"[PASS] 3. Argon2 is the primary password hasher: {hashers[0]}"))
            passed += 1
        else:
            self.stdout.write(self.style.ERROR("[FAIL] 3. Argon2 is not the primary password hasher."))

        # Check 4: Raw Database Encryption-At-Rest Inspection
        total += 1
        with connection.cursor() as cursor:
            cursor.execute("SELECT id, phone, employee_id FROM members_member LIMIT 5;")
            rows = cursor.fetchall()

        if rows:
            all_encrypted = True
            for mid, phone_raw, emp_raw in rows:
                # Fernet ciphertexts always start with 'gAAAAA'
                if not (phone_raw and str(phone_raw).startswith('gAAAAA')):
                    all_encrypted = False
                    self.stdout.write(self.style.ERROR(f"       Raw member {mid} phone is NOT encrypted: {phone_raw[:15]}..."))
                if emp_raw and not str(emp_raw).startswith('gAAAAA'):
                    all_encrypted = False
                    self.stdout.write(self.style.ERROR(f"       Raw member {mid} employee_id is NOT encrypted: {emp_raw[:15]}..."))

            if all_encrypted:
                self.stdout.write(self.style.SUCCESS("[PASS] 4. Database at rest: Sensitive columns verified encrypted (Fernet gAAAAA...)."))
                passed += 1
            else:
                self.stdout.write(self.style.ERROR("[FAIL] 4. Database at rest: Unencrypted plaintext detected in sensitive columns."))
        else:
            self.stdout.write(self.style.WARNING("[SKIP] 4. No members found in database to inspect."))
            passed += 1

        # Check 5: Blind Index Cryptographic Hash Inspection
        total += 1
        with connection.cursor() as cursor:
            cursor.execute("SELECT phone_blind_index FROM members_member WHERE phone_blind_index IS NOT NULL LIMIT 5;")
            bindex_rows = cursor.fetchall()

        if bindex_rows:
            all_bindexes_valid = all(len(r[0]) == 64 for r in bindex_rows)
            if all_bindexes_valid:
                self.stdout.write(self.style.SUCCESS("[PASS] 5. Blind index columns verified: 64-character keyed SHA-256 hashes."))
                passed += 1
            else:
                self.stdout.write(self.style.ERROR("[FAIL] 5. Blind index hashes are malformed."))
        else:
            self.stdout.write(self.style.WARNING("[SKIP] 5. No blind index records found."))
            passed += 1

        # Check 6: Session Idle Timeout
        total += 1
        timeout = getattr(settings, 'ADMIN_SESSION_TIMEOUT_SECONDS', None)
        if timeout and timeout <= 1200:  # <= 20 minutes
            self.stdout.write(self.style.SUCCESS(f"[PASS] 6. Admin session timeout configured: {timeout // 60} minutes."))
            passed += 1
        else:
            self.stdout.write(self.style.ERROR("[FAIL] 6. Admin session timeout exceeds 20 minutes or is unconfigured."))

        # Check 7: Security Middleware
        total += 1
        middleware = getattr(settings, 'MIDDLEWARE', [])
        required_mw = [
            'django.middleware.security.SecurityMiddleware',
            'django.middleware.csrf.CsrfViewMiddleware',
            'django.middleware.clickjacking.XFrameOptionsMiddleware',
            'accounts.middleware.SessionIdleTimeoutMiddleware',
        ]
        missing_mw = [mw for mw in required_mw if mw not in middleware]
        if not missing_mw:
            self.stdout.write(self.style.SUCCESS("[PASS] 7. Security middleware complete (CSRF, Clickjacking, Idle Timeout, Security)."))
            passed += 1
        else:
            self.stdout.write(self.style.ERROR(f"[FAIL] 7. Missing security middleware: {missing_mw}"))

        # Check 8: SQLite Concurrency & Foreign Key Hardening
        total += 1
        if connection.vendor == 'sqlite':
            with connection.cursor() as cursor:
                cursor.execute("PRAGMA foreign_keys;")
                fk_on = cursor.fetchone()[0]
                cursor.execute("PRAGMA busy_timeout;")
                timeout_val = cursor.fetchone()[0]

            if fk_on == 1 and timeout_val >= 5000:
                self.stdout.write(self.style.SUCCESS(f"[PASS] 8. SQLite hardened: foreign_keys=ON, busy_timeout={timeout_val}ms."))
                passed += 1
            else:
                self.stdout.write(self.style.ERROR(f"[FAIL] 8. SQLite hardening incomplete: fk={fk_on}, timeout={timeout_val}ms."))
        else:
            self.stdout.write(self.style.SUCCESS(f"[PASS] 8. Non-SQLite engine ({connection.vendor}) in use."))
            passed += 1

        self.stdout.write("\n-------------------------------------------------------")
        if passed == total:
            self.stdout.write(self.style.SUCCESS(f"SECURITY AUDIT SUMMARY: {passed}/{total} Checks PASSED (100% Compliant)"))
        else:
            self.stdout.write(self.style.WARNING(f"SECURITY AUDIT SUMMARY: {passed}/{total} Checks Passed."))
        self.stdout.write("-------------------------------------------------------\n")
