"""
Django settings for EduBac project.
Plateforme d'apprentissage des mathématiques — Django + Groq LLM
"""

from pathlib import Path
import os
from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Charger les variables d'environnement depuis .env
load_dotenv(BASE_DIR / '.env')

# Production must provide DJANGO_SECRET_KEY through its private environment.
# SESSION_SECRET and the explicit fallback are development-only.
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY') or os.getenv('SESSION_SECRET')
if not SECRET_KEY:
    if os.getenv('DJANGO_PRODUCTION') == '1':
        from django.core.exceptions import ImproperlyConfigured
        raise ImproperlyConfigured('DJANGO_SECRET_KEY est obligatoire en production.')
    SECRET_KEY = 'development-only-not-for-production'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv('DEBUG', 'True').lower() in ('true', '1', 'yes')

ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')
    if host.strip()
]

# Allow the current development preview without accepting arbitrary hosts.
if DEBUG and os.getenv('DJANGO_PRODUCTION') != '1':
    _preview_host = os.getenv('REPLIT_DEV_DOMAIN', '').strip()
    if _preview_host:
        ALLOWED_HOSTS.append(_preview_host)
        CSRF_TRUSTED_ORIGINS = [f'https://{_preview_host}']

# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Applications EduBac
    'accounts',
    'education',
    'quizzes',
    'classrooms',
    'ai',
    'notifications',
    'chat',
    'whiteboard',
    'channels',
]

MIDDLEWARE = [
    'quizzes.performance.GenerationTimingMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'accounts.middleware.SimpleSessionAuthMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'accounts.context_processors.student_sidebar',
                'chat.context_processors.chat_unread',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# Database
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization — Interface en français
LANGUAGE_CODE = 'fr-fr'
TIME_ZONE = 'Africa/Casablanca'
USE_I18N = True
USE_TZ = True

# Static & Media
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Custom User model
AUTH_USER_MODEL = 'accounts.User'

# ---------------------------------------------------------------------------
# AI providers (clés uniquement côté serveur — jamais exposées au frontend)
# ---------------------------------------------------------------------------
AI_DEFAULT_PROVIDER = os.getenv('AI_DEFAULT_PROVIDER', 'groq')

GROQ_API_KEY = os.getenv('GROQ_API_KEY', '')
# Llama 3.1 8B Instant and Llama 3.3 70B are gone from Groq free and developer
# tiers. gpt-oss-20b is the replacement. The provider asks for low reasoning
# effort because those tokens count against the TPM limit.
# Quality alternative: openai/gpt-oss-120b or qwen/qwen3.8-27b.
GROQ_MODEL = os.getenv('GROQ_MODEL', 'openai/gpt-oss-20b')
QUIZ_SEMANTIC_CHECK_ENABLED = os.getenv(
    'QUIZ_SEMANTIC_CHECK_ENABLED', 'false',
).strip().lower() in ('1', 'true', 'yes', 'on')
# Question repetition is allowed; mathematical and answer-choice checks remain active.
QUIZ_DUPLICATE_CHECK_ENABLED = False
QUIZ_LESSON_CONTEXT_CHARS = int(os.getenv('QUIZ_LESSON_CONTEXT_CHARS', '5000'))
QUIZ_GROQ_REQUEST_TOKEN_BUDGET = int(os.getenv('QUIZ_GROQ_REQUEST_TOKEN_BUDGET', '7500'))
QUIZ_MAX_QUESTIONS = int(os.getenv('QUIZ_MAX_QUESTIONS', '20'))

OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY', '')
OPENROUTER_MODEL = os.getenv('OPENROUTER_MODEL', 'openrouter/free')

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')
GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-2.0-flash')

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')
OPENAI_MODEL = os.getenv('OPENAI_MODEL', 'gpt-4o-mini')

XAI_API_KEY = os.getenv('XAI_API_KEY', '')
XAI_MODEL = os.getenv('XAI_MODEL', 'grok-3-mini')

# E-mail : Gmail SMTP pour les vérifications, notifications et réinitialisations.
# ---------------------------------------------------------------------------
EMAIL_BACKEND = os.getenv(
    'EMAIL_BACKEND',
    'django.core.mail.backends.smtp.EmailBackend',
).strip()
EMAIL_HOST = os.getenv('EMAIL_HOST', 'smtp.gmail.com').strip()
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '587'))
EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'True').strip().lower() in (
    'true', '1', 'yes',
)
EMAIL_USE_SSL = os.getenv('EMAIL_USE_SSL', 'False').strip().lower() in (
    'true', '1', 'yes',
)
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '').strip()
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '').strip()
EMAIL_TIMEOUT = int(os.getenv('EMAIL_TIMEOUT', '20'))
EMAIL_DIAGNOSTIC_TRACEBACK = os.getenv(
    'EMAIL_DIAGNOSTIC_TRACEBACK', 'False'
).strip().lower() in ('true', '1', 'yes')
DEFAULT_FROM_EMAIL = (
    os.getenv('DEFAULT_FROM_EMAIL', '').strip() or EMAIL_HOST_USER
)
SERVER_EMAIL = (
    os.getenv('SERVER_EMAIL', '').strip() or DEFAULT_FROM_EMAIL
)
EMAIL_NOTIFICATIONS_ENABLED = os.getenv('EMAIL_NOTIFICATIONS_ENABLED', 'True').lower() in ('true', '1', 'yes')
_site_url_default = 'http://127.0.0.1:8000'
_replit_dev_domain = os.getenv('REPLIT_DEV_DOMAIN', '').strip().strip('/')
if os.getenv('DJANGO_PRODUCTION') != '1' and _replit_dev_domain:
    _site_url_default = f'https://{_replit_dev_domain}'
SITE_URL = os.getenv('SITE_URL', _site_url_default).strip().rstrip('/')
_email_expiry_hours = os.getenv('EMAIL_VERIFICATION_EXPIRY_HOURS')
_email_token_max_age = os.getenv('EMAIL_VERIFICATION_TOKEN_MAX_AGE')
if _email_expiry_hours is not None:
    EMAIL_VERIFICATION_TOKEN_MAX_AGE = max(
        60, int(_email_expiry_hours) * 60 * 60
    )
else:
    EMAIL_VERIFICATION_TOKEN_MAX_AGE = max(
        60, int(_email_token_max_age or '172800')
    )
EMAIL_VERIFICATION_RESEND_COOLDOWN = max(
    0, int(os.getenv('EMAIL_VERIFICATION_RESEND_COOLDOWN', '60'))
)
EMAIL_VERIFICATION_IP_HOURLY_LIMIT = max(
    1, int(os.getenv('EMAIL_VERIFICATION_IP_HOURLY_LIMIT', '10'))
)


# ---- Production helpers ----
# PostgreSQL : définir DATABASE_URL=postgres://user:pass@host:5432/edubac
_database_url = os.getenv('DATABASE_URL', '').strip()
if _database_url.startswith('postgres'):
    # format simple postgres://user:pass@host:port/db
    import re
    m = re.match(
        r'postgres(?:ql)?://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)',
        _database_url,
    )
    if m:
        DATABASES = {
            'default': {
                'ENGINE': 'django.db.backends.postgresql',
                'NAME': m.group(5),
                'USER': m.group(1),
                'PASSWORD': m.group(2),
                'HOST': m.group(3),
                'PORT': m.group(4),
            }
        }

# Sécurité production (activer avec DJANGO_PRODUCTION=1)
if os.getenv('DJANGO_PRODUCTION') == '1':
    DEBUG = False
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    X_FRAME_OPTIONS = 'DENY'


# ---------------------------------------------------------------------------
# Django Channels (WebSocket) — InMemory pour le dev (pas de Redis requis)
# ---------------------------------------------------------------------------
ASGI_APPLICATION = 'config.asgi.application'
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels.layers.InMemoryChannelLayer',
    },
}

# Quiz and email diagnostics exclude prompts, credentials, tokens, and recipients.
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'email_trace': {
            'format': '%(asctime)s %(levelname)s %(name)s %(message)s',
        },
    },
    'handlers': {
        'quiz_console': {'class': 'logging.StreamHandler'},
        'email_console': {
            'class': 'logging.StreamHandler',
            'formatter': 'email_trace',
        },
    },
    'loggers': {
        'ai.services': {'handlers': ['quiz_console'], 'level': 'INFO', 'propagate': False},
        'quizzes.generation': {'handlers': ['quiz_console'], 'level': 'INFO', 'propagate': False},
        'accounts.views': {
            'handlers': ['email_console'],
            'level': 'INFO',
            'propagate': False,
        },
        'accounts.email_verification': {
            'handlers': ['email_console'],
            'level': 'INFO',
            'propagate': False,
        },
        'config.email_backend': {
            'handlers': ['email_console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}
