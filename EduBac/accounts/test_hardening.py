import os
import tempfile
from io import StringIO
from pathlib import Path
from unittest import mock

from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from accounts.models import User


class LoginThrottleTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username='omar', email='omar@example.test', password='Bon-mot-2026!',
                                             role='student')
        self.user.approval_status = 'approved'
        self.user.email_verified = True
        self.user.save()

    def tearDown(self):
        cache.clear()

    def post(self, password, username='omar'):
        return self.client.post(reverse('accounts:login'), {'username': username, 'password': password})

    def test_wrong_password_message_mentions_username(self):
        self.assertContains(self.post('faux'), 'Nom d’utilisateur ou mot de passe incorrect.')

    def test_account_is_paused_after_repeated_failures_even_with_the_right_password(self):
        for _ in range(8):
            self.post('faux')
        response = self.post('Bon-mot-2026!')
        self.assertContains(response, 'Trop de tentatives de connexion')
        self.assertNotIn('user_id', self.client.session)
        # Un autre élève (même connexion du lycée) n'est pas bloqué.
        User.objects.create_user(username='salma', password='Autre-mot-2026!', role='student',
                                 approval_status='approved', email_verified=True)
        self.assertEqual(self.post('Autre-mot-2026!', username='salma').status_code, 302)

    def test_success_resets_the_counter(self):
        for _ in range(7):
            self.post('faux')
        self.post('Bon-mot-2026!')
        self.client.logout()
        for _ in range(7):
            self.post('faux')
        self.assertNotContains(self.post('faux'), 'Trop de tentatives')


class BackupRotationTests(TestCase):
    def test_keeps_only_the_most_recent_backups(self):
        with tempfile.TemporaryDirectory() as home:
            folder = Path(home) / 'backups' / 'edubac'
            folder.mkdir(parents=True)
            for day in range(1, 6):
                (folder / f'db_202601{day:02d}_000000_000000.sqlite3').write_bytes(b'x')
            with mock.patch.dict(os.environ, {'HOME': home}), \
                    mock.patch('pathlib.Path.home', return_value=Path(home)):
                call_command('backup_db', keep=3, stdout=StringIO())
            names = sorted(p.name for p in folder.glob('db_*.sqlite3'))
            self.assertEqual(len(names), 3)
            self.assertNotIn('db_20260101_000000_000000.sqlite3', names)
            self.assertTrue(any(name.startswith('db_2026') and '0101' not in name for name in names))
