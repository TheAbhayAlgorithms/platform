"""
Django settings for RailClub Connect project.
Membership & Events Management Platform for Railway Employees.
"""

from pathlib import Path
from decouple import config, Csv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Quick-start development settings - unsuitable for production
SECRET_KEY = config('SECRET_KEY', default='django-insecure-dev-key-change-in-production')
DEBUG = config('DEBUG', default=True, cast=bool)

ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1,testserver', cast=Csv())

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Platform Apps
    'core.apps.CoreConfig',
    'accounts.apps.AccountsConfig',
    'members.apps.MembersConfig',
    'plans.apps.PlansConfig',
    'payments.apps.PaymentsConfig',
    'renewals.apps.RenewalsConfig',
    'portal.apps.PortalConfig',
    'notifications.apps.NotificationsConfig',
    'reports.apps.ReportsConfig',
    'events.apps.EventsConfig',
    'bookings.apps.BookingsConfig',
    'polls.apps.PollsConfig',
    'expenses.apps.ExpensesConfig',
    'backups.apps.BackupsConfig',
]

BACKUP_STORAGE_DIR = BASE_DIR / 'backups_storage'
BACKUP_RETENTION_DAYS = 30




MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'accounts.middleware.SessionIdleTimeoutMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ADMIN_SESSION_TIMEOUT_SECONDS = 20 * 60  # 20 minutes idle timeout

ROOT_URLCONF = 'railclub.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'core.context_processors.platform_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'railclub.wsgi.application'

# Database configuration
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# Password hashing: Argon2 is primary
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.Argon2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher',
    'django.contrib.auth.hashers.BCryptSHA256PasswordHasher',
]

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {'min_length': 8},
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization & Localization
LANGUAGE_CODE = config('LANGUAGE_CODE', default='en-in')
TIME_ZONE = config('TIME_ZONE', default='Asia/Kolkata')
USE_I18N = True
USE_L10N = False
USE_TZ = True

DATE_FORMAT = 'd-m-Y'
DATE_INPUT_FORMATS = ['%d-%m-%Y', '%Y-%m-%d']
DATETIME_FORMAT = 'd-m-Y H:i:s'

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Media files
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Session Security (Configured for Module 1 hardening)
SESSION_COOKIE_AGE = 20 * 60  # 20 minutes idle timeout
SESSION_SAVE_EVERY_REQUEST = True
SESSION_COOKIE_HTTPONLY = True

# Platform Specific Configuration
FIELD_ENCRYPTION_KEY = config('FIELD_ENCRYPTION_KEY', default='')
BLIND_INDEX_SALT = config('BLIND_INDEX_SALT', default='')

WHATSAPP_PROVIDER = config('WHATSAPP_PROVIDER', default='mock')
WHATSAPP_SENDER_NUMBER = config('WHATSAPP_SENDER_NUMBER', default='7039145304')
WHATSAPP_API_TOKEN = config('WHATSAPP_API_TOKEN', default='')
WHATSAPP_PHONE_NUMBER_ID = config('WHATSAPP_PHONE_NUMBER_ID', default='')
WHATSAPP_BUSINESS_ACCOUNT_ID = config('WHATSAPP_BUSINESS_ACCOUNT_ID', default='')
WHATSAPP_WEBHOOK_VERIFY_TOKEN = config('WHATSAPP_WEBHOOK_VERIFY_TOKEN', default='')

INSTITUTE_NAME = "RailClub Connect"
