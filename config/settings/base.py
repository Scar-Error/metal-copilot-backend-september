from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# ---------------------------------------------------------------------------
# Django Core
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'rest_framework_simplejwt',
    'corsheaders',
    'authentication',
    'rfq',
    'contacts',
    'microsoft_auth',
    'tasks',
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

ROOT_URLCONF = 'config.urls'

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
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
AUTH_USER_MODEL = 'authentication.CustomUser'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# ---------------------------------------------------------------------------
# Internationalization
# ---------------------------------------------------------------------------
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Europe/Rome'
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static & Media files
# ---------------------------------------------------------------------------
STATIC_URL = 'static/'
MEDIA_ROOT = BASE_DIR / 'media'
MEDIA_URL = '/media/'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ---------------------------------------------------------------------------
# Django REST Framework
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_PAGINATION_CLASS': 'config.pagination.StandardResultsSetPagination',
    'PAGE_SIZE': 20,
}

# ---------------------------------------------------------------------------
# SimpleJWT
# ---------------------------------------------------------------------------
from datetime import timedelta

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=30),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN': True,
    'ALGORITHM': 'HS256',
    'AUTH_HEADER_TYPES': ('Bearer',),
    'AUTH_HEADER_NAME': 'HTTP_AUTHORIZATION',
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
}

# ---------------------------------------------------------------------------
# Microsoft OAuth2 / Graph
# ---------------------------------------------------------------------------
MICROSOFT_CLIENT_ID = os.environ.get('MICROSOFT_CLIENT_ID', '')
MICROSOFT_CLIENT_SECRET = os.environ.get('MICROSOFT_CLIENT_SECRET', '')
MICROSOFT_TENANT_ID = os.environ.get('MICROSOFT_TENANT_ID', 'common')
MICROSOFT_GRAPH_API_URL = 'https://graph.microsoft.com/v1.0'
# Where Microsoft sends the browser once the user finishes linking. This MUST be
# the BACKEND url, and it must match a redirect URI registered on the Azure app.
MICROSOFT_REDIRECT_URI = os.environ.get(
    'MICROSOFT_REDIRECT_URI',
    'http://localhost:8000/api/auth/microsoft/callback/',
)

# Where the backend redirects the browser AFTER the token is stored. This is the
# FRONTEND url, not the backend one. The path is appended, so a trailing slash
# here would produce '//auth/callback'.
FRONTEND_URL = os.environ.get('FRONTEND_URL', 'http://localhost:5173').rstrip('/')

# Frontend route the callback lands on.
MICROSOFT_SUCCESS_REDIRECT_PATH = os.environ.get(
    'MICROSOFT_SUCCESS_REDIRECT_PATH',
    '/auth/callback',
)

# ---------------------------------------------------------------------------
# Business Central
# ---------------------------------------------------------------------------
BC_API_URL = os.environ.get('BC_API_URL', 'https://api.businesscentral.dynamics.com/v2.0')
BC_ODATA_URL = os.environ.get('BC_ODATA_URL', '')
BC_COMPANY_NAME = os.environ.get('BC_COMPANY_NAME', '')
BC_SYNC_ENABLED = os.environ.get('BC_SYNC_ENABLED', 'False').lower() == 'true'

# ---------------------------------------------------------------------------
# AI
# ---------------------------------------------------------------------------
# AI provider switch: 'anthropic' (default) or 'openai'. Drives both the
# client and the model used for classification + extraction.
AI_PROVIDER = os.environ.get('AI_PROVIDER', 'anthropic').strip().lower()
if AI_PROVIDER not in ('anthropic', 'openai'):
    AI_PROVIDER = 'anthropic'

OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')

# Models selected per provider (see rfq/ai_providers.py). Kept as settings so
# they can be inspected/overridden without touching the provider module.
ANTHROPIC_MODEL = os.environ.get('ANTHROPIC_MODEL', 'claude-haiku-4-5')
OPENAI_MODEL = os.environ.get('OPENAI_MODEL', 'gpt-5.4-nano')

# Stronger model used ONLY for the Round-2 image-details vision pass (small
# nameplate/label text is read more reliably by a larger model).
ANTHROPIC_VISION_MODEL = os.environ.get('ANTHROPIC_VISION_MODEL', 'claude-sonnet-4-6')
OPENAI_VISION_MODEL = os.environ.get('OPENAI_VISION_MODEL', 'gpt-5.4-mini')

# ---------------------------------------------------------------------------
# Celery (background task broker — email pulls run off the request thread)
# ---------------------------------------------------------------------------
CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE
# Run tasks synchronously in-process (useful for local dev/tests without a worker).
CELERY_TASK_ALWAYS_EAGER = os.environ.get('CELERY_TASK_ALWAYS_EAGER', 'false').lower() == 'true'
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 660
CELERY_TASK_SOFT_TIME_LIMIT = 600
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True

# ---------------------------------------------------------------------------
# Email (fallback — primary email goes through Graph API)
# ---------------------------------------------------------------------------
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'bc_sync': {
            'format': '%(asctime)s %(message)s',
            'datefmt': '%Y-%m-%d %H:%M:%S',
        },
    },
    'handlers': {
        'console_utf8': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'stream': 'ext://sys.stdout',
            'formatter': 'bc_sync',
        },
        'bc_sync': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': BASE_DIR / 'logs' / 'bc_sync.log',
            'formatter': 'bc_sync',
            'encoding': 'utf-8',
        },
        'email_polling': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': BASE_DIR / 'logs' / 'email_polling.log',
            'formatter': 'bc_sync',
            'encoding': 'utf-8',
        },
    },
    'loggers': {
        'bc_sync': {
            'handlers': ['bc_sync', 'console_utf8'],
            'level': 'INFO',
            'propagate': False,
        },
        'rfq': {
            'handlers': ['email_polling', 'console_utf8'],
            'level': 'INFO',
            'propagate': False,
        },
        'microsoft_auth': {
            'handlers': ['email_polling', 'console_utf8'],
            'level': 'INFO',
            'propagate': False,
        },
        'celery': {
            'handlers': ['email_polling', 'console_utf8'],
            'level': 'INFO',
            'propagate': False,
        },
    },
    'root': {
        'handlers': ['console_utf8'],
        'level': 'INFO',
    },
}
