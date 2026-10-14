import hmac
import hashlib
import re
from django.conf import settings
from django.db import models
from django.core.exceptions import ValidationError
from cryptography.fernet import Fernet, InvalidToken

def get_fernet():
    key = getattr(settings, 'FIELD_ENCRYPTION_KEY', '')
    if not key:
        raise ValueError("FIELD_ENCRYPTION_KEY is not configured in settings/environment.")
    if isinstance(key, str):
        key = key.encode('utf-8')
    return Fernet(key)

def get_blind_index_salt():
    salt = getattr(settings, 'BLIND_INDEX_SALT', '')
    if not salt:
        raise ValueError("BLIND_INDEX_SALT is not configured in settings/environment.")
    if isinstance(salt, str):
        salt = salt.encode('utf-8')
    return salt

def encrypt_value(raw_value: str) -> str:
    """Encrypt a string using Fernet (AES-256-CBC with HMAC)."""
    if raw_value is None:
        return None
    raw_str = str(raw_value)
    fernet = get_fernet()
    encrypted_bytes = fernet.encrypt(raw_str.encode('utf-8'))
    return encrypted_bytes.decode('utf-8')

def decrypt_value(encrypted_token: str) -> str:
    """Decrypt a Fernet token back to string."""
    if encrypted_token is None:
        return None
    try:
        fernet = get_fernet()
        decrypted_bytes = fernet.decrypt(str(encrypted_token).encode('utf-8'))
        return decrypted_bytes.decode('utf-8')
    except InvalidToken:
        return ""

def compute_blind_index(value: str) -> str:
    """
    Compute a keyed HMAC-SHA256 blind index for fast exact-match lookup
    without decrypting all records in the database.
    """
    if not value:
        return ""
    salt = get_blind_index_salt()
    # Normalize by trimming and lowercasing for consistent hashing
    normalized = str(value).strip().lower()
    return hmac.new(salt, normalized.encode('utf-8'), hashlib.sha256).hexdigest()

def normalize_phone(phone: str) -> str:
    """
    Normalizes Indian mobile numbers into standard format: +91XXXXXXXXXX.
    Rejects invalid numbers.
    """
    if not phone:
        return ""
    # Strip any spaces, dashes, parentheses
    cleaned = re.sub(r'[\s\-\(\)]', '', str(phone).strip())
    if cleaned.startswith('+91'):
        raw_digits = cleaned[3:]
    elif cleaned.startswith('91') and len(cleaned) == 12:
        raw_digits = cleaned[2:]
    elif cleaned.startswith('0') and len(cleaned) == 11:
        raw_digits = cleaned[1:]
    else:
        raw_digits = cleaned

    if not re.fullmatch(r'[6-9]\d{9}', raw_digits):
        raise ValidationError(f"Invalid Indian mobile number: '{phone}'. Must be a valid 10-digit number starting with 6-9.")

    return f"+91{raw_digits}"

class EncryptedCharField(models.CharField):
    """
    Django field that transparently encrypts values when saving to the database
    and decrypts them upon retrieval.
    """
    description = "Fernet encrypted char field"

    def from_db_value(self, value, expression, connection):
        if value is None or value == '':
            return value
        return decrypt_value(value)

    def to_python(self, value):
        if value is None or value == '':
            return value
        return value

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value is None or value == '':
            return value
        # Don't double encrypt if already encrypted token
        if isinstance(value, str) and value.startswith('gAAAAA'):
            return value
        return encrypt_value(value)
