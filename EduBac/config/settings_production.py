"""Réglages de production pour PythonAnywhere et les déploiements WSGI."""

import os
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from django.core.exceptions import ImproperlyConfigured

# Force le mode production avant le chargement des réglages communs.
os.environ['DJANGO_PRODUCTION'] = '1'

from .settings import *  # noqa: E402,F403


def _env_bool(name, default=False):
    value = os.getenv(name)
    return default if value is None else value.strip().lower() in {
        '1', 'true', 'yes', 'on',
    }


def _csv(name):
    return [
        item.strip()
        for item in os.getenv(name, '').split(',')
        if item.strip()
    ]


DEBUG = False

SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', '').strip()
if (
    not SECRET_KEY
    or SECRET_KEY.lower() in {'change-me-in-production', 'replace-me', 'your-secret-key'}
    or SECRET_KEY.startswith('django-insecure-')
):
    raise ImproperlyConfigured(
        'Définissez une vraie DJANGO_SECRET_KEY dans le fichier .env privé.'
    )

ALLOWED_HOSTS = _csv('ALLOWED_HOSTS')
if (
    not ALLOWED_HOSTS
    or '*' in ALLOWED_HOSTS
    or any(host.lower() in {'localhost', '127.0.0.1'} for host in ALLOWED_HOSTS)
):
    raise ImproperlyConfigured(
        'ALLOWED_HOSTS doit contenir les domaines de production exacts, sans joker.'
    )

CSRF_TRUSTED_ORIGINS = _csv('CSRF_TRUSTED_ORIGINS')

# PythonAnywhere termine TLS devant l'application WSGI.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = _env_bool('SECURE_SSL_REDIRECT', True)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SECURE_HSTS_SECONDS = int(os.getenv('SECURE_HSTS_SECONDS', '0'))
if SECURE_HSTS_SECONDS < 0:
    raise ImproperlyConfigured('SECURE_HSTS_SECONDS ne peut pas être négatif.')
SECURE_HSTS_INCLUDE_SUBDOMAINS = _env_bool(
    'SECURE_HSTS_INCLUDE_SUBDOMAINS', False
)
SECURE_HSTS_PRELOAD = _env_bool('SECURE_HSTS_PRELOAD', False)

# Le projet fonctionne sans serveur de base de données avec SQLite. MySQL est
# disponible en option si l'offre PythonAnywhere du compte le permet.
database_engine = os.getenv('DATABASE_ENGINE', '').strip().lower()
database_url = os.getenv('DATABASE_URL', '').strip()

if database_engine == 'mysql':
    required_mysql = ('MYSQL_DATABASE', 'MYSQL_USER', 'MYSQL_PASSWORD', 'MYSQL_HOST')
    missing_mysql = [name for name in required_mysql if not os.getenv(name)]
    if missing_mysql:
        raise ImproperlyConfigured(
            'La configuration MySQL est incomplète : renseignez MYSQL_DATABASE, '
            'MYSQL_USER, MYSQL_PASSWORD et MYSQL_HOST.'
        )
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': os.environ['MYSQL_DATABASE'],
            'USER': os.environ['MYSQL_USER'],
            'PASSWORD': os.environ['MYSQL_PASSWORD'],
            'HOST': os.environ['MYSQL_HOST'],
            'PORT': os.getenv('MYSQL_PORT', '3306'),
            'OPTIONS': {'charset': 'utf8mb4'},
            'CONN_MAX_AGE': 60,
        }
    }
elif database_engine == 'sqlite' or (
    not database_engine and not database_url
):
    sqlite_path = os.getenv('SQLITE_PATH', '').strip()
    db_path = Path(sqlite_path).expanduser() if sqlite_path else BASE_DIR / 'db.sqlite3'
    if not db_path.is_absolute():
        raise ImproperlyConfigured('SQLITE_PATH doit être un chemin absolu.')
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': db_path,
            'CONN_MAX_AGE': 0,
        }
    }
elif database_engine in {'postgres', 'postgresql', ''} and database_url:
    parsed = urlparse(database_url)
    if parsed.scheme not in {'postgres', 'postgresql'} or not parsed.hostname or not parsed.path.strip('/'):
        raise ImproperlyConfigured('DATABASE_URL PostgreSQL est invalide.')
    query = parse_qs(parsed.query)
    options = {
        key: values[-1]
        for key, values in query.items()
        if key in {'sslmode', 'target_session_attrs'}
    }
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': unquote(parsed.path.lstrip('/')),
            'USER': unquote(parsed.username or ''),
            'PASSWORD': unquote(parsed.password or ''),
            'HOST': parsed.hostname,
            'PORT': str(parsed.port or 5432),
            'OPTIONS': options,
            'CONN_MAX_AGE': 60,
        }
    }
elif database_engine in {'postgres', 'postgresql'}:
    raise ImproperlyConfigured(
        'DATABASE_ENGINE=postgresql exige une DATABASE_URL PostgreSQL valide.'
    )
else:
    raise ImproperlyConfigured('DATABASE_ENGINE doit être sqlite, mysql ou postgresql.')

# Les dossiers restent dans l'arborescence existante par défaut. Un chemin
# séparé n'est utilisé que si l'exploitant l'a explicitement configuré.
media_root_value = os.getenv('MEDIA_ROOT', '').strip()
if media_root_value:
    MEDIA_ROOT = Path(media_root_value).expanduser()
    if not MEDIA_ROOT.is_absolute():
        raise ImproperlyConfigured('MEDIA_ROOT doit être un chemin absolu.')

STATIC_URL = '/static/'
MEDIA_URL = '/media/'
