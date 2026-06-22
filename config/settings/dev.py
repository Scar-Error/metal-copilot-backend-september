import os
import sys

from .base import *

# ---------------------------------------------------------------------------
# Security — relaxed for development
# ---------------------------------------------------------------------------
SECRET_KEY = os.environ.get(
    'SECRET_KEY',
    'django-insecure-dev-mode-not-for-production',
)

DEBUG = os.environ.get('DEBUG', 'True').strip().lower() in ('true', '1', 'yes')

ALLOWED_HOSTS = ['*']

# ---------------------------------------------------------------------------
# CORS — permissive for local frontend development
# ---------------------------------------------------------------------------
CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = True

# ---------------------------------------------------------------------------
# Database — SQLite for local dev
# ---------------------------------------------------------------------------
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# ---------------------------------------------------------------------------
# Startup validation (dev — warn but don't crash)
# ---------------------------------------------------------------------------
_REQUIRED_DEV = {
    'MICROSOFT_CLIENT_ID': MICROSOFT_CLIENT_ID,
    'MICROSOFT_CLIENT_SECRET': MICROSOFT_CLIENT_SECRET,
}

for _name, _val in _REQUIRED_DEV.items():
    if not _val:
        print(
            f'WARNING: {_name} is not set. '
            f'Microsoft authentication will not work.',
            file=sys.stderr,
        )
