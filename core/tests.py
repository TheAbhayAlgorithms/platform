import pytest
from django.conf import settings
from django.test import Client
from django.core.exceptions import ValidationError
from django.contrib.auth.hashers import make_password, identify_hasher
from core.encryption import (
    encrypt_value,
    decrypt_value,
    compute_blind_index,
    normalize_phone,
)

@pytest.mark.django_db
class TestProjectSkeletonSmoke:
    """Smoke tests for the RailClub Connect project skeleton."""

    def test_settings_configuration(self):
        """Verify timezone, hashers, and security parameters."""
        assert settings.TIME_ZONE == 'Asia/Kolkata'
        assert settings.USE_TZ is True
        assert settings.PASSWORD_HASHERS[0] == 'django.contrib.auth.hashers.Argon2PasswordHasher'
        assert settings.WHATSAPP_SENDER_NUMBER == '7039145304'

    def test_argon2_password_hashing(self):
        """Verify passwords are hashed with Argon2 by default."""
        hashed = make_password('test-secure-pass-123')
        hasher = identify_hasher(hashed)
        assert hasher.algorithm == 'argon2'
        assert not hashed.startswith('test-secure-pass')

    def test_field_encryption_roundtrip(self):
        """Verify Fernet encryption and decryption roundtrip."""
        secret_emp_id = "WR-ENG-9842"
        token = encrypt_value(secret_emp_id)
        
        # Raw value must not contain the plaintext
        assert secret_emp_id not in token
        assert token.startswith('gAAAAA')
        
        # Decryption reproduces the exact original string
        decrypted = decrypt_value(token)
        assert decrypted == secret_emp_id

    def test_blind_index_deterministic_hash(self):
        """Verify keyed HMAC blind index produces exact matching deterministic hash."""
        phone1 = "9876543210"
        phone2 = " 9876543210 "
        idx1 = compute_blind_index(phone1)
        idx2 = compute_blind_index(phone2)
        assert idx1 == idx2
        assert len(idx1) == 64  # SHA-256 hex digest length

        # Different phone produces different blind index
        idx_diff = compute_blind_index("9876543211")
        assert idx1 != idx_diff

    def test_indian_phone_normalization(self):
        """Verify Indian 10-digit phone normalization to +91XXXXXXXXXX."""
        assert normalize_phone("9876543210") == "+919876543210"
        assert normalize_phone("+919876543210") == "+919876543210"
        assert normalize_phone("09876543210") == "+919876543210"
        assert normalize_phone("98765-43210") == "+919876543210"
        assert normalize_phone("+91 98765 43210") == "+919876543210"

        # Invalid numbers should raise ValidationError
        with pytest.raises(ValidationError):
            normalize_phone("1234567890")  # does not start with 6-9

        with pytest.raises(ValidationError):
            normalize_phone("98765")  # too short

    def test_home_page_and_health_check(self):
        """Verify public home view and health check endpoint."""
        client = Client()
        
        home_res = client.get('/')
        assert home_res.status_code == 200
        assert b"RailClub Connect" in home_res.content

        health_res = client.get('/health/')
        assert health_res.status_code == 200
        assert health_res.json() == {'status': 'ok', 'app': 'RailClub Connect'}
