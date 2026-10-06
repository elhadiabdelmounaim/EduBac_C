"""Isolated browser-test database; never use the development/production DB."""
from config.settings import *  # noqa: F403

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_SSL_REDIRECT = False
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
EMAIL_NOTIFICATIONS_ENABLED = False
