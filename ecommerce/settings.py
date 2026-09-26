"""
Django settings for the Mahitaji e-commerce platform.

All secrets and environment-specific values come from the `.env` file (see
`.env.example`). Nothing sensitive should be committed here.
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(os.path.join(BASE_DIR, '.env'))


def env_bool(name, default=False):
    return os.getenv(name, str(default)).strip().lower() in ('1', 'true', 'yes', 'on')


def env_list(name, default=''):
    return [item.strip() for item in os.getenv(name, default).split(',') if item.strip()]


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------
SECRET_KEY = os.getenv('SECRET_KEY') or 'dev-only-insecure-key-change-me'
DEBUG = env_bool('DEBUG', False)
ALLOWED_HOSTS = env_list('ALLOWED_HOSTS', 'localhost,127.0.0.1,.ngrok-free.app' if DEBUG else '')
CSRF_TRUSTED_ORIGINS = env_list(
    'CSRF_TRUSTED_ORIGINS',
    'http://localhost:8000,http://127.0.0.1:8000,https://*.ngrok-free.app' if DEBUG else '',
)

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    'rest_framework',
    'corsheaders',
    'import_export',
    'core',
    'django_daraja',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# WhiteNoise serves the collected static files in production. With DEBUG on,
# runserver serves them straight from ``static/`` via the staticfiles finders,
# so WhiteNoise is left out (it would only warn that STATIC_ROOT is missing).
if not DEBUG:
    MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')

ROOT_URLCONF = 'ecommerce.urls'

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
                'core.context_processors.shop',
            ],
        },
    },
]

WSGI_APPLICATION = 'ecommerce.wsgi.application'

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': os.getenv('DB_NAME'),
        'USER': os.getenv('DB_USER'),
        'PASSWORD': os.getenv('DB_PASSWORD'),
        'HOST': os.getenv('DB_HOST', '127.0.0.1'),
        'PORT': os.getenv('DB_PORT', '3306'),
        'OPTIONS': {'charset': 'utf8mb4'},
        'CONN_MAX_AGE': 60,
    }
}

# The test-suite runs against an in-memory SQLite database so it never needs
# CREATE DATABASE rights on MySQL. Set USE_SQLITE=true to develop without MySQL.
if 'test' in sys.argv or env_bool('USE_SQLITE'):
    DATABASES['default'] = {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:' if 'test' in sys.argv else BASE_DIR / 'db.sqlite3',
    }

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 8}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LOGIN_REDIRECT_URL = 'dashboard'
LOGOUT_REDIRECT_URL = 'home'
LOGIN_URL = 'login'

SESSION_COOKIE_AGE = 60 * 60 * 24 * 14  # two weeks, so carts survive between visits
SESSION_SAVE_EVERY_REQUEST = False

# ---------------------------------------------------------------------------
# Internationalisation
# ---------------------------------------------------------------------------
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Africa/Nairobi'
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static & media
# ---------------------------------------------------------------------------
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {
        # Production: content-hashed filenames so WhiteNoise can serve them with
        # immutable, far-future cache headers (and gzip/brotli variants).
        'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage' if not DEBUG
        else 'django.contrib.staticfiles.storage.StaticFilesStorage',
    },
}

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ---------------------------------------------------------------------------
# REST framework
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.IsAuthenticatedOrReadOnly'],
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework.authentication.BasicAuthentication',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 24,
}
CORS_ALLOWED_ORIGINS = env_list('CORS_ALLOWED_ORIGINS')
CORS_ALLOW_ALL_ORIGINS = DEBUG and not CORS_ALLOWED_ORIGINS

# ---------------------------------------------------------------------------
# M-Pesa (django-daraja reads these names)
# ---------------------------------------------------------------------------
MPESA_ENVIRONMENT = os.getenv('MPESA_ENVIRONMENT', 'sandbox')
MPESA_SHORTCODE = os.getenv('MPESA_SHORTCODE', '174379')
MPESA_EXPRESS_SHORTCODE = os.getenv('MPESA_EXPRESS_SHORTCODE', MPESA_SHORTCODE)
MPESA_SHORTCODE_TYPE = os.getenv('MPESA_SHORTCODE_TYPE', 'paybill')
MPESA_CONSUMER_KEY = os.getenv('MPESA_CONSUMER_KEY', '')
MPESA_CONSUMER_SECRET = os.getenv('MPESA_CONSUMER_SECRET', '')
MPESA_PASSKEY = os.getenv('MPESA_PASSKEY', '')
MPESA_CALLBACK_URL = os.getenv('MPESA_CALLBACK_URL', '')
MPESA_INITIATOR_USERNAME = os.getenv('MPESA_INITIATOR_USERNAME', 'testapi')
MPESA_INITIATOR_SECURITY_CREDENTIAL = os.getenv('MPESA_INITIATOR_SECURITY_CREDENTIAL', '')

# ---------------------------------------------------------------------------
# Messages, email, AI, site info
# ---------------------------------------------------------------------------
from django.contrib.messages import constants as messages  # noqa: E402

MESSAGE_TAGS = {
    messages.DEBUG: 'muted',
    messages.INFO: 'info',
    messages.SUCCESS: 'success',
    messages.WARNING: 'warning',
    messages.ERROR: 'danger',
}

EMAIL_BACKEND = os.getenv('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = os.getenv('EMAIL_HOST', '')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '587'))
EMAIL_USE_TLS = env_bool('EMAIL_USE_TLS', True)
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'Mahitaji <no-reply@mahitaji.co.ke>')
ORDER_NOTIFICATION_EMAIL = os.getenv('ORDER_NOTIFICATION_EMAIL', '')

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')
GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-3.8-flash')

# Shopping assistant (core/assistant.py). Counters live in the cache: with the
# default in-process cache each Gunicorn worker counts separately, so point
# CACHES at Redis/Memcached in production for exact limits.
ASSISTANT_RATE_LIMIT = int(os.getenv('ASSISTANT_RATE_LIMIT', '20'))          # messages per visitor per window
ASSISTANT_RATE_WINDOW = int(os.getenv('ASSISTANT_RATE_WINDOW', '600'))       # seconds
ASSISTANT_DAILY_LLM_LIMIT = int(os.getenv('ASSISTANT_DAILY_LLM_LIMIT', '500'))  # model calls per day, all visitors
ASSISTANT_MAX_MESSAGE_LENGTH = int(os.getenv('ASSISTANT_MAX_MESSAGE_LENGTH', '500'))
ASSISTANT_TIMEOUT_SECONDS = float(os.getenv('ASSISTANT_TIMEOUT_SECONDS', '12'))
ASSISTANT_HISTORY_TURNS = int(os.getenv('ASSISTANT_HISTORY_TURNS', '8'))

CART_SESSION_ID = 'cart'

SITE_INFO = {
    'name': 'Mahitaji',
    'legal_name': 'Mahitaji Enterprises Ltd',
    'tagline': 'Wholesale & retail FMCG distribution across Kenya',
    'phone': '+254 750 530 130',
    'phone_href': 'tel:+254750530130',
    'whatsapp': 'https://wa.me/254750530130',
    'email': 'info@mahitaji.co.ke',
    'address': 'Prabhaki Industrial Park, Baba Dogo Road, Ruaraka, Nairobi',
    'po_box': 'P.O. Box 48312 - 00100, Nairobi, Kenya',
    'hours': 'Mon – Fri 08:00 – 17:00 · Sat 08:00 – 13:00',
    'free_delivery_threshold': 20000,
}

# ---------------------------------------------------------------------------
# Security (production only)
# ---------------------------------------------------------------------------
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT = env_bool('SECURE_SSL_REDIRECT', True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {'simple': {'format': '%(levelname)s %(asctime)s %(name)s: %(message)s'}},
    'handlers': {'console': {'class': 'logging.StreamHandler', 'formatter': 'simple'}},
    'root': {'handlers': ['console'], 'level': 'INFO'},
    'loggers': {
        'django': {'handlers': ['console'], 'level': 'WARNING', 'propagate': False},
        'core': {'handlers': ['console'], 'level': 'DEBUG' if DEBUG else 'INFO', 'propagate': False},
    },
}
