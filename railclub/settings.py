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

ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1,testserver,.vercel.app', cast=Csv())
CSRF_TRUSTED_ORIGINS = config('CSRF_TRUSTED_ORIGINS', default='https://*.vercel.app,http://127.0.0.1,http://localhost', cast=Csv())

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
    'transfers.apps.TransfersConfig',
]

IS_VERCEL = config('VERCEL', default=False, cast=bool)
if IS_VERCEL:
    BACKUP_STORAGE_DIR = Path('/tmp/backups_storage')
else:
    BACKUP_STORAGE_DIR = BASE_DIR / 'backups_storage'

BACKUP_RETENTION_DAYS = 30




MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
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

# Database configuration (Local SQLite default, Supabase/PostgreSQL when DATABASE_URL is provided)
DATABASE_URL = config('DATABASE_URL', default=None)

if DATABASE_URL:
    try:
        import dj_database_url
        DATABASES = {
            'default': dj_database_url.config(
                default=DATABASE_URL,
                conn_max_age=600,
                ssl_require=True
            )
        }
    except ImportError:
        import urllib.parse as urlparse
        url = urlparse.urlparse(DATABASE_URL)
        DATABASES = {
            'default': {
                'ENGINE': 'django.db.backends.postgresql',
                'NAME': url.path[1:],
                'USER': url.username,
                'PASSWORD': url.password,
                'HOST': url.hostname,
                'PORT': url.port or '5432',
                'OPTIONS': {'sslmode': 'require'},
            }
        }
else:
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
STATICFILES_STORAGE = 'whitenoise.storage.CompressedStaticFilesStorage'

# Media files
MEDIA_URL = '/media/'
MEDIA_ROOT = Path('/tmp/media') if IS_VERCEL else BASE_DIR / 'media'

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Session & HTTP Security Hardening (Production Ready)
SESSION_COOKIE_AGE = 20 * 60  # 20 minutes idle timeout
SESSION_SAVE_EVERY_REQUEST = True
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'SAMEORIGIN'

# Logging Configuration
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{asctime}] {levelname} [{name}:{lineno}] {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': config('DJANGO_LOG_LEVEL', default='INFO'),
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'railclub': {
            'handlers': ['console'],
            'level': 'DEBUG',
            'propagate': True,
        },
    },
}

# Platform Specific Configuration
FIELD_ENCRYPTION_KEY = config('FIELD_ENCRYPTION_KEY', default='npzvqAKfTwZy8EXzhOzHD9pXpxpwtTMlbU69Joihi0Y=')
BLIND_INDEX_SALT = config('BLIND_INDEX_SALT', default='67a8ec60e2c26af03bac261791311c3ea8a68cac24c8e0954962316c126905f6')

WHATSAPP_PROVIDER = config('WHATSAPP_PROVIDER', default='mock')
WHATSAPP_SENDER_NUMBER = config('WHATSAPP_SENDER_NUMBER', default='7039145304')
WHATSAPP_API_TOKEN = config('WHATSAPP_API_TOKEN', default='')
WHATSAPP_PHONE_NUMBER_ID = config('WHATSAPP_PHONE_NUMBER_ID', default='')
WHATSAPP_BUSINESS_ACCOUNT_ID = config('WHATSAPP_BUSINESS_ACCOUNT_ID', default='')
WHATSAPP_WEBHOOK_VERIFY_TOKEN = config('WHATSAPP_WEBHOOK_VERIFY_TOKEN', default='')

INSTITUTE_NAME = "RailClub Connect"
