import os

DJANGO_ENV = os.environ.get('DJANGO_ENV', 'dev')

if DJANGO_ENV == 'production':
    from .production import *
else:
    from .dev import *
