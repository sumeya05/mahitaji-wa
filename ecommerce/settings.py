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
DEBUG = env_bool('DEBUG', False)
SECRET_KEY = os.getenv('SECRET_KEY')
if not SECRET_KEY:
    if not DEBUG and 'test' not in sys.argv:
        from django.core.exceptions import ImproperlyConfigured
        raise ImproperlyConfigured("Set SECRET_KEY in .env before running with DEBUG off.")
    SECRET_KEY = 'dev-only-insecure-key-change-me'
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
    'rest_framework.authtoken',   # mobile app sign-in (core/views/mobile.py)
    'corsheaders',
    'import_export',
    'core',
    'fleet',                      # Mahitaji Fleet masters (fleet/models.py)
    'django_daraja',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'core.middleware.StaffSessionTimeoutMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'core.middleware.ContentSecurityPolicyMiddleware',
]

# The admin lives at this path. Set ADMIN_URL in production to something unguessable
# (e.g. "office-7f3k/") so bots scanning /admin/ never find the sign-in page.
ADMIN_URL = os.getenv('ADMIN_URL', 'admin/').strip().strip('/') + '/'

# Behind Nginx the client address arrives in X-Forwarded-For (Nginx overwrites it with the
# real peer address, so it can be trusted). Without a proxy, trusting it would let anyone
# spoof their address and dodge the sign-in and API limits.
TRUST_X_FORWARDED_FOR = env_bool('TRUST_X_FORWARDED_FOR', not DEBUG)

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

if 'test' in sys.argv:
    # Real password hashing is deliberately slow; the test-suite creates many users.
    PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']

LOGIN_REDIRECT_URL = 'dashboard'
LOGOUT_REDIRECT_URL = 'home'
LOGIN_URL = 'login'

SESSION_COOKIE_AGE = 60 * 60 * 24 * 14  # two weeks, so carts survive between visits
SESSION_SAVE_EVERY_REQUEST = False
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'
# Staff accounts can reach the admin, so their sessions end after this much inactivity
# (customers keep the two-week session above). See core.middleware.
STAFF_SESSION_IDLE_SECONDS = int(float(os.getenv('STAFF_SESSION_IDLE_HOURS', '8')) * 3600)

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
# Sign-in, M-Pesa and assistant rate limits, and the navigation cache, all live here.
# Set REDIS_URL in production: the in-process fallback is per Gunicorn worker, so limits
# would be counted separately by each worker.
REDIS_URL = os.getenv('REDIS_URL', '').strip()
if REDIS_URL and 'test' not in sys.argv:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.redis.RedisCache',
            'LOCATION': REDIS_URL,
            'KEY_PREFIX': 'mahitaji',
            'TIMEOUT': 300,
        }
    }
    # Sessions are read from Redis and written through to the database, which stays the
    # source of truth (a Redis restart does not sign anyone out).
    SESSION_ENGINE = 'django.contrib.sessions.backends.cached_db'
else:
    CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'mahitaji'}}

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
    # Session auth only: HTTP Basic would let scripts brute-force passwords through the API.
    'DEFAULT_AUTHENTICATION_CLASSES': ['rest_framework.authentication.SessionAuthentication'],
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {'anon': '60/min', 'user': '300/min'},
    'NUM_PROXIES': 1 if TRUST_X_FORWARDED_FOR else None,
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
if 'test' in sys.argv:
    # The test-suite must never talk to Safaricom; tests that need M-Pesa switch it on with mocks.
    MPESA_CALLBACK_URL = MPESA_CONSUMER_KEY = MPESA_CONSUMER_SECRET = ''
MPESA_TIMEOUT = int(os.getenv('MPESA_TIMEOUT', '30'))                # seconds per call to Safaricom
MPESA_PROMPT_INTERVAL = int(os.getenv('MPESA_PROMPT_INTERVAL', '20'))  # seconds between two prompts for one order
# Payment prompts one customer may send per hour, across all their orders. Each prompt lands on a
# phone of the customer's choosing, so an uncapped account could pester strangers in the shop's name.
MPESA_PROMPTS_PER_HOUR = int(os.getenv('MPESA_PROMPTS_PER_HOUR', '6'))

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
SERVER_EMAIL = os.getenv('SERVER_EMAIL', DEFAULT_FROM_EMAIL)
# A stuck mail server must not stall checkout: give up after this many seconds.
EMAIL_TIMEOUT = int(os.getenv('EMAIL_TIMEOUT', '10'))
# Order confirmations are sent from a background thread so the customer is not kept waiting
# on SMTP. Off during tests, where the outbox is inspected right after checkout.
EMAIL_IN_BACKGROUND = env_bool('EMAIL_IN_BACKGROUND', not DEBUG) and 'test' not in sys.argv
# "Name:email,Name:email" — these addresses get an email for every server error.
ADMINS = [tuple(item.split(':', 1)) if ':' in item else (item, item) for item in env_list('ADMINS')]
MANAGERS = ADMINS
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
COUPON_SESSION_ID = 'coupon'

# Stock: at or below this many units (in the product's unit of sale) a line shows "Low stock".
LOW_STOCK_THRESHOLD = int(os.getenv('LOW_STOCK_THRESHOLD', '5'))

# Unpaid M-Pesa orders older than this are cancelled by `manage.py expire_unpaid_orders`
# (run on a timer), which puts the stock they hold back on sale.
UNPAID_ORDER_EXPIRY_HOURS = int(os.getenv('UNPAID_ORDER_EXPIRY_HOURS', '24'))
# Cash-on-delivery orders that staff have not confirmed (moved past Pending) within this many
# hours are cancelled by the same command, so an account cannot hold stock indefinitely by
# placing orders it never means to take. 0 disables the expiry.
UNCONFIRMED_COD_ORDER_EXPIRY_HOURS = int(os.getenv('UNCONFIRMED_COD_ORDER_EXPIRY_HOURS', '72'))
# Orders one account may have awaiting payment or confirmation at the same time.
MAX_OPEN_ORDERS = int(os.getenv('MAX_OPEN_ORDERS', '5'))
# The public price list CSV is rebuilt from the catalogue at most this often (it is also
# dropped whenever a product, category, brand or stock entry changes).
PRICE_LIST_CACHE_SECONDS = int(os.getenv('PRICE_LIST_CACHE_SECONDS', '300'))
# Cells in admin exports that start with = + - @ would run as formulas in Excel: escape them.
IMPORT_EXPORT_ESCAPE_FORMULAE_ON_EXPORT = True

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
    'kra_pin': os.getenv('COMPANY_KRA_PIN', ''),   # printed on order documents when set
}

# ---------------------------------------------------------------------------
# Security (production only)
# ---------------------------------------------------------------------------
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'
X_FRAME_OPTIONS = 'DENY'
FILE_UPLOAD_PERMISSIONS = 0o644
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024   # forms; file uploads stream to disk separately
DATA_UPLOAD_MAX_NUMBER_FILES = 500               # bulk product-photo uploads in the admin
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT = env_bool('SECURE_SSL_REDIRECT', True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    # Start at 30 days; once HTTPS has been stable for a while set SECURE_HSTS_SECONDS=31536000.
    SECURE_HSTS_SECONDS = int(os.getenv('SECURE_HSTS_SECONDS', str(60 * 60 * 24 * 30)))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = env_bool('SECURE_HSTS_PRELOAD', False)

# Preload is a deliberate opt-in (see .env.example), so its warning must not fail the deploy
# check; every other warning does (deploy/scripts/deploy.sh runs with --fail-level WARNING).
SILENCED_SYSTEM_CHECKS = ['security.W021']

# Content-Security-Policy for the storefront (core.middleware.ContentSecurityPolicyMiddleware).
# Inline <script> blocks in the templates carry nonce="{{ request.csp_nonce }}"; everything
# else must come from this origin or the hosts listed here. The admin and the browsable API
# ship their own inline scripts, so they are left out.
CSP_EXEMPT_PREFIXES = ['/' + ADMIN_URL, '/data/']
CSP_DIRECTIVES = {
    'default-src': ["'self'"],
    'script-src': ["'self'"],  # the per-request nonce is added by the middleware
    'style-src': ["'self'", "'unsafe-inline'", 'https://fonts.googleapis.com', 'https://cdnjs.cloudflare.com'],
    'font-src': ["'self'", 'https://fonts.gstatic.com', 'https://cdnjs.cloudflare.com'],
    'img-src': ["'self'", 'data:'],
    'connect-src': ["'self'"],
    'frame-src': ['https://www.google.com'],  # the map on the Location page
    'frame-ancestors': ["'none'"],
    'form-action': ["'self'"],
    'base-uri': ["'self'"],
    'object-src': ["'none'"],
}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {'simple': {'format': '%(levelname)s %(asctime)s %(name)s: %(message)s'}},
    'filters': {'require_debug_false': {'()': 'django.utils.log.RequireDebugFalse'}},
    'handlers': {
        'console': {'class': 'logging.StreamHandler', 'formatter': 'simple'},
        # Server errors (500s) are emailed to ADMINS in production.
        'mail_admins': {'class': 'django.utils.log.AdminEmailHandler', 'level': 'ERROR',
                        'filters': ['require_debug_false']},
    },
    'root': {'handlers': ['console'], 'level': 'INFO'},
    'loggers': {
        'django': {'handlers': ['console', 'mail_admins'], 'level': 'WARNING', 'propagate': False},
        # Suspicious requests (bad Host header, CSRF failures, ...) are worth seeing but not emailing.
        'django.security': {'handlers': ['console'], 'level': 'WARNING', 'propagate': False},
        'core': {'handlers': ['console', 'mail_admins'], 'level': 'DEBUG' if DEBUG else 'INFO', 'propagate': False},
    },
}
