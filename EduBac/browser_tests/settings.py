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

# Par défaut : SQLite en mémoire. BROWSER_TEST_POSTGRES=1 garde la base PostgreSQL de
# DATABASE_URL ; Django crée alors une base de test séparée (test_…), jamais la vraie.
if os.environ.get("BROWSER_TEST_POSTGRES") != "1":
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
else:
    # Nom explicite : l'outil de test de Channels ajoute sinon « test_ » deux fois
    # dans le processus du serveur ASGI (test_test_…).
    DATABASES["default"].setdefault("TEST", {})["NAME"] = "test_" + DATABASES["default"]["NAME"]  # noqa: F405
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_SSL_REDIRECT = False
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
EMAIL_NOTIFICATIONS_ENABLED = False
