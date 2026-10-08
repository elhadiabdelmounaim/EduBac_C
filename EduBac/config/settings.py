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

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'django-insecure-_1mw2(s926f#%sz4av8rks(#skvo=$s)6(lg!@kdqfg9szea9m')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv('DEBUG', 'True').lower() in ('true', '1', 'yes')

ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')

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
STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
MEDIA_URL = 'media/'
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
QUIZ_LESSON_CONTEXT_CHARS = int(os.getenv('QUIZ_LESSON_CONTEXT_CHARS', '5000'))
QUIZ_GROQ_REQUEST_TOKEN_BUDGET = int(os.getenv('QUIZ_GROQ_REQUEST_TOKEN_BUDGET', '7500'))
QUIZ_MAX_QUESTIONS = int(os.getenv('QUIZ_MAX_QUESTIONS', '10'))

OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY', '')
OPENROUTER_MODEL = os.getenv('OPENROUTER_MODEL', 'openrouter/free')

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')
GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-2.0-flash')

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')
OPENAI_MODEL = os.getenv('OPENAI_MODEL', 'gpt-4o-mini')

XAI_API_KEY = os.getenv('XAI_API_KEY', '')
XAI_MODEL = os.getenv('XAI_MODEL', 'grok-3-mini')

# Email (console pour le développement)
# ---------------------------------------------------------------------------
# Configuration e-mail
# ---------------------------------------------------------------------------
# En développement : affiche les e-mails dans la console
# En production : configurer SMTP via les variables d'environnement
EMAIL_BACKEND = os.getenv(
    'EMAIL_BACKEND',
    'django.core.mail.backends.console.EmailBackend'
)
EMAIL_HOST = os.getenv('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '587'))
EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'True').lower() in ('true', '1', 'yes')
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'EduBac <noreply@edubac.ma>')
SERVER_EMAIL = DEFAULT_FROM_EMAIL
EMAIL_NOTIFICATIONS_ENABLED = os.getenv('EMAIL_NOTIFICATIONS_ENABLED', 'True').lower() in ('true', '1', 'yes')
SITE_URL = os.getenv('SITE_URL', 'http://127.0.0.1:8000')


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
