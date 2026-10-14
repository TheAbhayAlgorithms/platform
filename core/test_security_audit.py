from datetime import date, timedelta
from decimal import Decimal
import pytest
from django.urls import reverse
from django.db import connection
from django.contrib.auth.models import User
from django.test import Client

from accounts.models import UserProfile, RoleChoices, AdminOTP
from members.models import Member, MemberStatus, DepartmentChoices
from plans.models import Plan, MemberPlanAssignment
from payments.models import Payment, PaymentMode, PaymentStatus
from portal.models import MemberOTP
from core.encryption import compute_blind_index, normalize_phone, encrypt_value, decrypt_value


@pytest.fixture
def superadmin_user(db):
    user = User.objects.create_user(username='sec_admin', password='AdminPassword@2026!')
    UserProfile.objects.create(user=user, role=RoleChoices.SUPER_ADMIN, phone='+919876543210')
    return user


@pytest.fixture
def accountant_user(db):
    user = User.objects.create_user(username='sec_acct', password='AcctPassword@2026!')
    UserProfile.objects.create(user=user, role=RoleChoices.ACCOUNTANT, phone='+919876543211')
    return user


@pytest.fixture
def eventmanager_user(db):
    user = User.objects.create_user(username='sec_event', password='EventPassword@2026!')
    UserProfile.objects.create(user=user, role=RoleChoices.EVENT_MANAGER, phone='+919876543212')
    return user


@pytest.fixture
def viewer_user(db):
    user = User.objects.create_user(username='sec_view', password='ViewPassword@2026!')
    UserProfile.objects.create(user=user, role=RoleChoices.VIEWER, phone='+919876543213')
    return user


@pytest.fixture
def audit_plan(db):
    return Plan.objects.create(
        name="Security Audit Plan",
        fee=Decimal('2400.00'),
        duration_months=12,
        is_active=True
    )


@pytest.fixture
def audit_member_one(db, audit_plan):
    m = Member.objects.create(
        name="Audit Member One",
        phone="+919876540001",
        employee_id="SEC-ENG-001",
        department=DepartmentChoices.ENGINEERING,
        status=MemberStatus.ACTIVE
    )
    a = MemberPlanAssignment.objects.create(
        member=m,
        plan=audit_plan,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        base_fee=audit_plan.fee,
        is_current=True
    )
    Payment.objects.create(
        member=m,
        plan_assignment=a,
        amount=Decimal('2400.00'),
        payment_mode=PaymentMode.UPI,
        reference_number="SEC-UTR-001",
        status=PaymentStatus.COMPLETED
    )
    return m


@pytest.fixture
def audit_member_two(db, audit_plan):
    m = Member.objects.create(
        name="Audit Member Two",
        phone="+919876540002",
        employee_id="SEC-COM-002",
        department=DepartmentChoices.COMMERCIAL,
        status=MemberStatus.DUE
    )
    a = MemberPlanAssignment.objects.create(
        member=m,
        plan=audit_plan,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        base_fee=audit_plan.fee,
        is_current=True
    )
    Payment.objects.create(
        member=m,
        plan_assignment=a,
        amount=Decimal('1000.00'),
        payment_mode=PaymentMode.CASH,
        reference_number="SEC-CASH-002",
        status=PaymentStatus.COMPLETED
    )
    return m


@pytest.mark.django_db
class TestFieldEncryptionAndDataAtRestAudit:
    def test_raw_database_inspection_proves_encryption_at_rest(self, audit_member_one):
        """
        Direct raw SQL query against SQLite/PostgreSQL to verify ciphertext.
        Checks that plaintext phone and employee ID NEVER appear in raw storage.
        """
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT phone, employee_id, phone_blind_index, employee_id_blind_index "
                "FROM members_member WHERE id = %s",
                [audit_member_one.id]
            )
            row = cursor.fetchone()

        raw_phone, raw_emp_id, phone_bindex, emp_bindex = row

        # Fernet ciphertext token header check
        assert raw_phone.startswith('gAAAAA'), "Phone must be encrypted with Fernet AES-256 token"
        assert raw_emp_id.startswith('gAAAAA'), "Employee ID must be encrypted with Fernet AES-256 token"

        # Plaintext absence check
        assert "+919876540001" not in raw_phone
        assert "9876540001" not in raw_phone
        assert "SEC-ENG-001" not in raw_emp_id

        # Blind index hash verification
        assert len(phone_bindex) == 64, "Blind index must be 64-hex-char SHA-256 hash"
        assert len(emp_bindex) == 64, "Blind index must be 64-hex-char SHA-256 hash"

        # Decryption round-trip check via ORM
        audit_member_one.refresh_from_db()
        assert audit_member_one.phone == "+919876540001"
        assert audit_member_one.employee_id == "SEC-ENG-001"

    def test_blind_index_is_keyed_and_deterministic(self):
        """Blind indexes must be deterministic for lookups but keyed with secret salt."""
        phone1 = "+919876540001"
        phone2 = "9876540001"
        # Normalization produces exact same blind index
        norm1 = normalize_phone(phone1)
        norm2 = normalize_phone(phone2)
        assert compute_blind_index(norm1) == compute_blind_index(norm2)


@pytest.mark.django_db
class TestArgon2PasswordSecurityAudit:
    def test_passwords_hashed_with_argon2(self, superadmin_user):
        """Verifies that user passwords in the DB start with argon2 algorithm prefix."""
        with connection.cursor() as cursor:
            cursor.execute("SELECT password FROM auth_user WHERE id = %s", [superadmin_user.id])
            stored_hash = cursor.fetchone()[0]

        assert stored_hash.startswith('argon2'), f"Expected Argon2 password hasher, found: {stored_hash[:15]}"
        assert superadmin_user.check_password('AdminPassword@2026!') is True
        assert superadmin_user.check_password('WrongPassword') is False


@pytest.mark.django_db
class TestOTPSecurityAudit:
    def test_admin_and_member_otps_stored_as_sha256_hashes(self, superadmin_user, audit_member_one):
        """Verifies that OTPs are never stored in plaintext in the database."""
        admin_code = AdminOTP.create_for_user(superadmin_user)
        member_code = MemberOTP.create_for_member(audit_member_one)

        with connection.cursor() as cursor:
            cursor.execute("SELECT otp_hash FROM accounts_adminotp WHERE user_id = %s", [superadmin_user.id])
            admin_stored = cursor.fetchone()[0]
            cursor.execute("SELECT otp_hash FROM portal_memberotp WHERE member_id = %s", [audit_member_one.id])
            member_stored = cursor.fetchone()[0]

        assert admin_stored != admin_code
        assert len(admin_stored) == 64
        assert admin_stored == AdminOTP.hash_otp(admin_code)

        assert member_stored != member_code
        assert len(member_stored) == 64
        assert member_stored == MemberOTP.hash_otp(member_code)


@pytest.mark.django_db
class TestRBACSecurityMatrixAudit:
    def _login_as(self, client, user):
        client.force_login(user)
        session = client.session
        session['user_id'] = user.id
        session['otp_verified'] = True
        session.save()

    def test_user_management_access_restricted_to_super_admin(self, client, superadmin_user, accountant_user, eventmanager_user, viewer_user):
        """User management URL (/admin-users/) allowed only for Super Admin; 403 for others."""
        url = reverse('accounts:user_list')

        self._login_as(client, superadmin_user)
        assert client.get(url).status_code == 200

        self._login_as(client, accountant_user)
        assert client.get(url).status_code == 403

        self._login_as(client, eventmanager_user)
        assert client.get(url).status_code == 403

        self._login_as(client, viewer_user)
        assert client.get(url).status_code == 403

    def test_member_soft_delete_restricted_to_super_admin(self, client, superadmin_user, accountant_user, eventmanager_user, viewer_user, audit_member_one):
        """Member deletion restricted to Super Admin; others rejected."""
        url = reverse('members:member_delete', args=[audit_member_one.id])

        self._login_as(client, viewer_user)
        assert client.get(url).status_code == 403

        self._login_as(client, eventmanager_user)
        assert client.get(url).status_code == 403

        self._login_as(client, accountant_user)
        assert client.get(url).status_code == 403

        self._login_as(client, superadmin_user)
        assert client.get(url).status_code == 200

    def test_payment_recording_restricted_to_super_admin_and_accountant(self, client, superadmin_user, accountant_user, eventmanager_user, viewer_user, audit_member_one):
        """Payments can only be recorded by Super Admin and Accountant."""
        url = reverse('payments:payment_record', args=[audit_member_one.id])

        self._login_as(client, viewer_user)
        assert client.get(url).status_code == 403

        self._login_as(client, eventmanager_user)
        assert client.get(url).status_code == 403

        self._login_as(client, accountant_user)
        assert client.get(url).status_code == 200

        self._login_as(client, superadmin_user)
        assert client.get(url).status_code == 200


@pytest.mark.django_db
class TestIDORAndSessionIsolationAudit:
    def test_idor_prevention_member_receipt_download(self, client, audit_member_one, audit_member_two):
        """
        Penetration test: Member One attempts to access Member Two's payment receipt
        by manipulating the payment ID parameter.
        Must return 404 (Not Found) without leaking the other member's receipt.
        """
        session = client.session
        session['member_authenticated'] = True
        session['member_id'] = audit_member_one.id
        session.save()

        # Target Member Two's receipt
        target_payment = audit_member_two.payments.first()
        attack_url = reverse('portal:download_receipt', args=[target_payment.id])

        resp = client.get(attack_url)
        assert resp.status_code == 404, "IDOR Vulnerability: Member accessed another member's receipt!"

    def test_member_portal_cannot_access_admin_dashboard(self, client, audit_member_one):
        """Member portal session must NOT grant access to admin dashboard."""
        session = client.session
        session['member_authenticated'] = True
        session['member_id'] = audit_member_one.id
        session.save()

        resp = client.get(reverse('accounts:dashboard'))
        assert resp.status_code == 302
        assert reverse('accounts:login') in resp.url

    def test_admin_session_cannot_access_member_portal_dashboard_without_otp(self, client, superadmin_user):
        """Staff login session cannot access member dashboard without member OTP."""
        client.force_login(superadmin_user)
        resp = client.get(reverse('portal:dashboard'))
        assert resp.status_code == 302
        assert reverse('portal:login') in resp.url


@pytest.mark.django_db
class TestCSRFAndClickjackingAudit:
    def test_post_without_csrf_token_is_rejected(self, audit_member_one):
        """Verifies CSRF middleware blocks POST without valid token."""
        csrf_client = Client(enforce_csrf_checks=True)
        resp = csrf_client.post(reverse('portal:login'), {'phone': '9876540001'})
        assert resp.status_code == 403  # CSRF verification failed

    def test_clickjacking_x_frame_options_header_present(self, client):
        """Verifies X-Frame-Options header is set to protect against UI redressing/clickjacking."""
        resp = client.get(reverse('home'))
        assert 'X-Frame-Options' in resp.headers
        assert resp.headers['X-Frame-Options'] in ['DENY', 'SAMEORIGIN']
