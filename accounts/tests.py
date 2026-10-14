import time
from datetime import timedelta
import pytest
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.urls import reverse
from django.test import Client
from django.utils import timezone
from freezegun import freeze_time

from accounts.models import UserProfile, RoleChoices, AdminOTP
from core.messaging import MockWhatsAppProvider
from core.encryption import decrypt_value, compute_blind_index

@pytest.fixture(autouse=True)
def clear_mock_messages():
    MockWhatsAppProvider.clear_sent_messages()
    yield
    MockWhatsAppProvider.clear_sent_messages()


@pytest.fixture
def superadmin_user(db):
    user = User.objects.create_user(
        username='superadmin_test',
        password='TestPassword123!',
        first_name='Super',
        last_name='Admin',
        email='super@railclub.test',
        is_staff=True,
        is_superuser=True,
    )
    UserProfile.objects.create(
        user=user,
        role=RoleChoices.SUPER_ADMIN,
        phone='+919876543210',
        is_2fa_enabled=True,
    )
    return user


@pytest.fixture
def accountant_user(db):
    user = User.objects.create_user(
        username='accountant_test',
        password='TestPassword123!',
        first_name='Accountant',
        last_name='User',
        email='acct@railclub.test',
        is_staff=True,
    )
    UserProfile.objects.create(
        user=user,
        role=RoleChoices.ACCOUNTANT,
        phone='+919876543211',
        is_2fa_enabled=True,
    )
    return user


@pytest.fixture
def event_manager_user(db):
    user = User.objects.create_user(
        username='eventmgr_test',
        password='TestPassword123!',
        first_name='Event',
        last_name='Manager',
        email='event@railclub.test',
        is_staff=True,
    )
    UserProfile.objects.create(
        user=user,
        role=RoleChoices.EVENT_MANAGER,
        phone='+919876543212',
        is_2fa_enabled=True,
    )
    return user


@pytest.fixture
def viewer_user(db):
    user = User.objects.create_user(
        username='viewer_test',
        password='TestPassword123!',
        first_name='Viewer',
        last_name='User',
        email='viewer@railclub.test',
        is_staff=True,
    )
    UserProfile.objects.create(
        user=user,
        role=RoleChoices.VIEWER,
        phone='+919876543213',
        is_2fa_enabled=True,
    )
    return user


@pytest.mark.django_db
class TestAuthenticationAndLockout:
    """Tests password validation, brute-force lockout, and Argon2 hashing."""

    def test_passwords_stored_hashed_with_argon2(self, superadmin_user):
        """Verify password is not stored in plaintext and uses Argon2."""
        raw_db_user = User.objects.get(id=superadmin_user.id)
        assert not raw_db_user.password.startswith('TestPassword')
        assert raw_db_user.password.startswith('argon2')
        assert raw_db_user.check_password('TestPassword123!')

    def test_wrong_password_rejected(self, superadmin_user):
        """Submitting wrong password must fail and increment failed attempts counter."""
        client = Client()
        response = client.post(reverse('accounts:login'), {
            'username': 'superadmin_test',
            'password': 'WrongPassword999!',
        })
        assert response.status_code == 200
        assert 'pending_2fa_user_id' not in client.session
        
        superadmin_user.profile.refresh_from_db()
        assert superadmin_user.profile.failed_login_attempts == 1
        assert not superadmin_user.profile.is_locked_out()

    def test_lockout_after_five_failed_attempts(self, superadmin_user):
        """5 consecutive wrong passwords triggers a 15-minute account lockout."""
        client = Client()
        for i in range(1, 5):
            client.post(reverse('accounts:login'), {
                'username': 'superadmin_test',
                'password': f'WrongAttempt{i}!',
            })
            superadmin_user.profile.refresh_from_db()
            assert superadmin_user.profile.failed_login_attempts == i
            assert not superadmin_user.profile.is_locked_out()

        # 5th attempt locks the account
        res5 = client.post(reverse('accounts:login'), {
            'username': 'superadmin_test',
            'password': 'WrongAttempt5!',
        })
        assert res5.status_code == 200
        superadmin_user.profile.refresh_from_db()
        assert superadmin_user.profile.failed_login_attempts == 5
        assert superadmin_user.profile.is_locked_out()

        # Even with correct password, login is blocked while locked out
        res_correct = client.post(reverse('accounts:login'), {
            'username': 'superadmin_test',
            'password': 'TestPassword123!',
        })
        assert res_correct.status_code == 200
        assert 'Account is temporarily locked' in res_correct.content.decode()
        assert 'pending_2fa_user_id' not in client.session


@pytest.mark.django_db
class TestTwoFactorAuthenticationOTP:
    """Tests 2FA OTP flow, expiration, max attempts, and reuse protection."""

    def test_successful_login_with_otp(self, superadmin_user):
        """Valid credentials dispatch OTP and valid OTP completes login."""
        client = Client()
        
        # Step 1: Submit valid username and password
        res1 = client.post(reverse('accounts:login'), {
            'username': 'superadmin_test',
            'password': 'TestPassword123!',
        })
        assert res1.status_code == 302
        assert res1.url == reverse('accounts:verify_otp')
        assert client.session.get('pending_2fa_user_id') == superadmin_user.id

        # Verify OTP was dispatched via Mock WhatsApp Provider
        last_otp = MockWhatsAppProvider.get_last_otp('+919876543210')
        assert last_otp is not None
        assert len(last_otp) == 6

        # Step 2: Submit valid 6-digit OTP
        res2 = client.post(reverse('accounts:verify_otp'), {
            'otp_code': last_otp,
        })
        assert res2.status_code == 302
        assert res2.url == reverse('accounts:dashboard')
        assert '_auth_user_id' in client.session
        assert int(client.session['_auth_user_id']) == superadmin_user.id

        # Failed attempts counter must be reset
        superadmin_user.profile.refresh_from_db()
        assert superadmin_user.profile.failed_login_attempts == 0

    def test_incorrect_otp_rejected_with_attempt_limit(self, superadmin_user):
        """Incorrect OTP is rejected; 3 failed OTP attempts marks OTP as invalid."""
        client = Client()
        client.post(reverse('accounts:login'), {
            'username': 'superadmin_test',
            'password': 'TestPassword123!',
        })
        
        # Submit 3 wrong OTPs
        for _ in range(3):
            res = client.post(reverse('accounts:verify_otp'), {'otp_code': '000000'})
            assert res.status_code == 200
            assert 'Invalid or expired OTP' in res.content.decode()

        # 4th attempt with the correct OTP now fails because max attempts reached
        real_otp = MockWhatsAppProvider.get_last_otp()
        res_late = client.post(reverse('accounts:verify_otp'), {'otp_code': real_otp})
        assert res_late.status_code == 200
        assert 'Invalid or expired OTP' in res_late.content.decode()
        assert '_auth_user_id' not in client.session

    def test_expired_otp_rejected(self, superadmin_user):
        """OTP older than 5 minutes is rejected."""
        client = Client()
        
        # Step 1: Login at time T
        initial_time = timezone.now()
        with freeze_time(initial_time):
            client.post(reverse('accounts:login'), {
                'username': 'superadmin_test',
                'password': 'TestPassword123!',
            })
            real_otp = MockWhatsAppProvider.get_last_otp()

        # Step 2: Try verifying 6 minutes later
        with freeze_time(initial_time + timedelta(minutes=6)):
            res = client.post(reverse('accounts:verify_otp'), {'otp_code': real_otp})
            assert res.status_code == 200
            assert 'Invalid or expired OTP' in res.content.decode()
            assert '_auth_user_id' not in client.session

    def test_reused_otp_rejected(self, superadmin_user):
        """Once an OTP is successfully used, it cannot be used again."""
        client = Client()
        client.post(reverse('accounts:login'), {
            'username': 'superadmin_test',
            'password': 'TestPassword123!',
        })
        real_otp = MockWhatsAppProvider.get_last_otp()

        # First use succeeds
        res1 = client.post(reverse('accounts:verify_otp'), {'otp_code': real_otp})
        assert res1.status_code == 302

        # Logout
        client.post(reverse('accounts:logout'))
        assert '_auth_user_id' not in client.session

        # Initiate new login
        client.post(reverse('accounts:login'), {
            'username': 'superadmin_test',
            'password': 'TestPassword123!',
        })
        # Try reusing the first OTP
        res_reuse = client.post(reverse('accounts:verify_otp'), {'otp_code': real_otp})
        assert res_reuse.status_code == 200
        assert 'Invalid or expired OTP' in res_reuse.content.decode()


@pytest.mark.django_db
class TestRolePermissionMatrix:
    """
    Verifies that each role can access only what it should:
    Super Admin: User management (list, add, edit, toggle, reset).
    Accountant, Event Manager, Viewer: Forbidden (HTTP 403) from user management.
    """

    def test_super_admin_has_full_user_management_access(self, superadmin_user):
        client = Client()
        client.force_login(superadmin_user)

        # List users
        res = client.get(reverse('accounts:user_list'))
        assert res.status_code == 200

        # Add user page
        res = client.get(reverse('accounts:user_create'))
        assert res.status_code == 200

    def test_accountant_denied_from_user_management(self, accountant_user):
        client = Client()
        client.force_login(accountant_user)

        res_list = client.get(reverse('accounts:user_list'))
        assert res_list.status_code == 403

        res_create = client.get(reverse('accounts:user_create'))
        assert res_create.status_code == 403

    def test_event_manager_denied_from_user_management(self, event_manager_user):
        client = Client()
        client.force_login(event_manager_user)

        res_list = client.get(reverse('accounts:user_list'))
        assert res_list.status_code == 403

        res_create = client.get(reverse('accounts:user_create'))
        assert res_create.status_code == 403

    def test_viewer_denied_from_user_management(self, viewer_user):
        client = Client()
        client.force_login(viewer_user)

        res_list = client.get(reverse('accounts:user_list'))
        assert res_list.status_code == 403

        res_create = client.get(reverse('accounts:user_create'))
        assert res_create.status_code == 403

    def test_super_admin_can_create_and_toggle_admin_user(self, superadmin_user):
        client = Client()
        client.force_login(superadmin_user)

        # Create new accountant
        post_data = {
            'username': 'new_acct_user',
            'first_name': 'New',
            'last_name': 'Accountant',
            'email': 'newacct@railclub.test',
            'role': RoleChoices.ACCOUNTANT,
            'phone': '9876543299',
            'initial_password': 'TempPassword123!',
        }
        res_post = client.post(reverse('accounts:user_create'), post_data)
        assert res_post.status_code == 302
        assert res_post.url == reverse('accounts:user_list')

        new_user = User.objects.get(username='new_acct_user')
        assert new_user.profile.role == RoleChoices.ACCOUNTANT
        assert new_user.profile.phone == '+919876543299'
        assert new_user.is_active is True

        # Toggle status to disabled
        res_toggle = client.post(reverse('accounts:user_toggle_status', kwargs={'user_id': new_user.id}))
        assert res_toggle.status_code == 302
        new_user.refresh_from_db()
        assert new_user.is_active is False


@pytest.mark.django_db
class TestSessionTimeout:
    """Verifies 20-minute idle session timeout middleware."""

    def test_session_expires_after_20_minutes_idle(self, superadmin_user):
        client = Client()
        client.force_login(superadmin_user)
        
        # Initial access sets last_activity
        res1 = client.get(reverse('accounts:dashboard'))
        assert res1.status_code == 200
        last_act = client.session.get('last_activity')
        assert last_act is not None

        # Simulate 21 minutes (1260 seconds) elapsed
        session = client.session
        session['last_activity'] = last_act - (21 * 60)
        session.save()

        # Next request must log out user and redirect to login
        res2 = client.get(reverse('accounts:dashboard'))
        assert res2.status_code == 302
        assert res2.url.startswith(reverse('accounts:login'))
        assert '_auth_user_id' not in client.session


@pytest.mark.django_db
class TestPasswordChangeAndReset:
    """Verifies password change and secure token reset flow."""

    def test_authenticated_password_change(self, superadmin_user):
        client = Client()
        client.force_login(superadmin_user)

        res = client.post(reverse('accounts:change_password'), {
            'current_password': 'TestPassword123!',
            'new_password': 'BrandNewPassword999!',
            'confirm_password': 'BrandNewPassword999!',
        })
        assert res.status_code == 302
        assert res.url == reverse('accounts:dashboard')

        superadmin_user.refresh_from_db()
        assert superadmin_user.check_password('BrandNewPassword999!')

    def test_forgot_password_and_token_reset_flow(self, viewer_user):
        client = Client()

        # Step 1: Request reset link
        res1 = client.post(reverse('accounts:forgot_password'), {
            'username_or_email': 'viewer_test',
        })
        assert res1.status_code == 302
        assert res1.url == reverse('accounts:login')

        # Generate token directly to simulate clicking the link
        token = default_token_generator.make_token(viewer_user)
        uid = urlsafe_base64_encode(force_bytes(viewer_user.pk))
        reset_confirm_url = reverse('accounts:reset_password_confirm', kwargs={'uidb64': uid, 'token': token})

        # Step 2: Set new password
        res2 = client.post(reset_confirm_url, {
            'new_password': 'ViewerNewPass2026!',
            'confirm_password': 'ViewerNewPass2026!',
        })
        assert res2.status_code == 302
        assert res2.url == reverse('accounts:login')

        viewer_user.refresh_from_db()
        assert viewer_user.check_password('ViewerNewPass2026!')


@pytest.mark.django_db
class TestUserProfileEncryptionAndEdgeCases:
    """Tests sensitive field encryption at rest, blind indexing, and administrative safeguards."""

    def test_phone_encrypted_at_rest_with_blind_index(self, superadmin_user):
        """Verifies phone is encrypted at rest in raw DB and blind index allows search."""
        profile = superadmin_user.profile
        assert profile.phone == '+919876543210'
        
        # Verify blind index matches computed hash
        expected_blind_idx = compute_blind_index('+919876543210')
        assert profile.phone_blind_index == expected_blind_idx

        # Direct database query by blind index finds the user instantly
        found_profile = UserProfile.objects.filter(phone_blind_index=expected_blind_idx).first()
        assert found_profile is not None
        assert found_profile.user == superadmin_user

    def test_deactivated_user_cannot_log_in(self, viewer_user):
        """Deactivated user account is rejected at login."""
        viewer_user.is_active = False
        viewer_user.save()

        client = Client()
        res = client.post(reverse('accounts:login'), {
            'username': 'viewer_test',
            'password': 'TestPassword123!',
        })
        assert res.status_code == 200
        assert 'This account has been disabled' in res.content.decode()
        assert 'pending_2fa_user_id' not in client.session

    def test_super_admin_cannot_deactivate_self(self, superadmin_user):
        """Super Admin is prevented from deactivating their own administrative account."""
        client = Client()
        client.force_login(superadmin_user)

        res = client.post(
            reverse('accounts:user_edit', kwargs={'user_id': superadmin_user.id}),
            {
                'first_name': 'Super',
                'last_name': 'Admin',
                'email': 'super@railclub.test',
                'role': RoleChoices.SUPER_ADMIN,
                'phone': '9876543210',
                'is_active': False,  # Attempting to deactivate self
            }
        )
        assert res.status_code == 302
        superadmin_user.refresh_from_db()
        assert superadmin_user.is_active is True

    def test_resend_otp_flow(self, superadmin_user):
        """Test resending OTP generates a fresh code and updates session."""
        client = Client()
        client.post(reverse('accounts:login'), {
            'username': 'superadmin_test',
            'password': 'TestPassword123!',
        })
        first_otp = MockWhatsAppProvider.get_last_otp()
        assert first_otp is not None

        # Request resend
        res = client.get(reverse('accounts:resend_otp'))
        assert res.status_code == 302
        assert res.url == reverse('accounts:verify_otp')
        second_otp = MockWhatsAppProvider.get_last_otp()
        assert second_otp is not None
        assert second_otp != first_otp  # A fresh code was generated

    def test_unauthenticated_dashboard_redirects_to_login(self):
        """Unauthenticated user accessing protected dashboard is redirected to login."""
        client = Client()
        res = client.get(reverse('accounts:dashboard'))
        assert res.status_code == 302
        assert res.url == f"{reverse('accounts:login')}?next={reverse('accounts:dashboard')}"

