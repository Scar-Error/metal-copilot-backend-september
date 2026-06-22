import os
import sys

from .base import *

# ---------------------------------------------------------------------------
# Security — strict for production
# ---------------------------------------------------------------------------
SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY:
    raise RuntimeError(
        'SECRET_KEY environment variable is required in production.'
    )

DEBUG = False

ALLOWED_HOSTS_RAW = os.environ.get('ALLOWED_HOSTS', '')
if not ALLOWED_HOSTS_RAW:
    raise RuntimeError(
        'ALLOWED_HOSTS environment variable is required in production. '
        'Separate multiple hosts with commas.'
    )
ALLOWED_HOSTS = [h.strip() for h in ALLOWED_HOSTS_RAW.split(',') if h.strip()]

# ---------------------------------------------------------------------------
# CORS — explicit origins only
# ---------------------------------------------------------------------------
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOW_CREDENTIALS = True

_CORS_RAW = os.environ.get('CORS_ALLOWED_ORIGINS', '')
if _CORS_RAW:
    CORS_ALLOWED_ORIGINS = [o.strip() for o in _CORS_RAW.split(',') if o.strip()]
else:
    CORS_ALLOWED_ORIGINS = []

# ---------------------------------------------------------------------------
# Database — PostgreSQL
# ---------------------------------------------------------------------------
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('DB_NAME'),
        'USER': os.environ.get('DB_USER'),
        'PASSWORD': os.environ.get('DB_PASSWORD'),
        'HOST': os.environ.get('DB_HOST', 'localhost'),
        'PORT': os.environ.get('DB_PORT', '5432'),
    }
}

# Validate database config
for _key in ('DB_NAME', 'DB_USER', 'DB_PASSWORD'):
    if not os.environ.get(_key):
        raise RuntimeError(f'{_key} environment variable is required in production.')

# ---------------------------------------------------------------------------
# Session & CSRF — HTTPS-only
# ---------------------------------------------------------------------------
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# ---------------------------------------------------------------------------
# Startup validation — fail early if critical config is missing
# ---------------------------------------------------------------------------
_REQUIRED_PROD = {
    'MICROSOFT_CLIENT_ID': MICROSOFT_CLIENT_ID,
    'MICROSOFT_CLIENT_SECRET': MICROSOFT_CLIENT_SECRET,
    'OPENAI_API_KEY': OPENAI_API_KEY,
}

for _name, _val in _REQUIRED_PROD.items():
    if not _val:
        raise RuntimeError(
            f'{_name} environment variable is required in production.'
        )
