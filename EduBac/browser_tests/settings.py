"""Isolated browser-test database; never use the development/production DB."""
import os
import shutil

from config.settings import *  # noqa: F403

# Navigateur des tests : CHROMIUM_EXECUTABLE s'il est défini, sinon Chromium ou Chrome installé.
if not os.environ.get("CHROMIUM_EXECUTABLE"):
    for _name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        if shutil.which(_name):
            os.environ["CHROMIUM_EXECUTABLE"] = shutil.which(_name)
            break

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_SSL_REDIRECT = False
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
EMAIL_NOTIFICATIONS_ENABLED = False
