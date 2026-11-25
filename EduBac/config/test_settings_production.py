"""Réglages de production avec MySQL : mode strict activé à chaque connexion (mysql.W002)."""
import json
import os
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase

BASE_DIR = Path(__file__).resolve().parent.parent


class ReglagesMySQLTests(SimpleTestCase):
    def test_mode_strict_mysql(self):
        env = {
            **os.environ,
            'DJANGO_SETTINGS_MODULE': 'config.settings_production',
            'DJANGO_SECRET_KEY': 'cle-de-test-' + 'x' * 50,
            'ALLOWED_HOSTS': 'edubac.example.org',
            'EMAIL_HOST_USER': 'test@example.org', 'EMAIL_HOST_PASSWORD': 'motdepasse',
            'DATABASE_ENGINE': 'mysql', 'MYSQL_DATABASE': 'u$edubac', 'MYSQL_USER': 'u',
            'MYSQL_PASSWORD': 'p', 'MYSQL_HOST': 'u.mysql.example.org',
        }
        code = ('import json, django; from django.conf import settings; '
                'print(json.dumps(settings.DATABASES["default"]["OPTIONS"]))')
        sortie = subprocess.run([sys.executable, '-c', code], cwd=BASE_DIR, env=env,
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(sortie.returncode, 0, sortie.stderr[-2000:])
        options = json.loads(sortie.stdout.strip().splitlines()[-1])
        self.assertEqual(options['charset'], 'utf8mb4')
        self.assertIn('STRICT_TRANS_TABLES', options['init_command'])
