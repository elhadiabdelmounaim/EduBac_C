"""Code de récupération et changement volontaire du mot de passe (sans e-mail)."""
import re

from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse

from .models import User
from .recovery import MAX_FAILURES

PASSWORD = 'AncienSecret2026!'
NEW = 'NouveauSecret2026!'
CODE_RE = re.compile(r'[A-HJ-KM-NP-Z2-9]{4}-[A-HJ-KM-NP-Z2-9]{4}-[A-HJ-KM-NP-Z2-9]{4}')
RECOVER = reverse('accounts:recover_with_code')


class RecoveryCodeTests(TestCase):
    def setUp(self):
        cache.clear()
        self.student = User.objects.create_user(
            username='salma.b', email='salma.b@example.test', password=PASSWORD,
            first_name='Salma', last_name='Bennani', role='student')

    def login(self, client=None, password=PASSWORD, username='salma.b'):
        client = client or self.client
        return client.post(reverse('accounts:login'), {'username': username, 'password': password})

    def issue(self, client=None):
        client = client or self.client
        response = client.post(reverse('accounts:recovery_code'))
        return CODE_RE.search(response.content.decode()).group(0)

    def recover(self, code, password=NEW, username='salma.b', client=None):
        return (client or Client()).post(RECOVER, {
            'username': username, 'code': code, 'new_password1': password, 'new_password2': password})

    # --- Code ---------------------------------------------------------------
    def test_student_without_code_is_offered_one_after_login(self):
        self.assertRedirects(self.login(), reverse('accounts:recovery_code') + '?premiere=1',
                             fetch_redirect_response=False)
        page = self.client.get(reverse('accounts:recovery_code') + '?premiere=1')
        self.assertContains(page, 'Afficher mon code')
        self.assertContains(page, 'Plus tard')
        code = self.issue()
        self.student.refresh_from_db()
        self.assertTrue(self.student.recovery_code_hash)
        self.assertNotIn(code.replace('-', ''), self.student.recovery_code_hash)
        self.client.get(reverse('accounts:logout'))
        self.assertRedirects(self.login(), reverse('accounts:dashboard'), fetch_redirect_response=False)

    def test_teacher_is_not_interrupted(self):
        User.objects.create_user(username='prof', email='prof@example.test', password=PASSWORD, role='teacher')
        response = self.login(username='prof')
        self.assertNotIn('code-de-recuperation', response['Location'])

    def test_new_code_replaces_the_old_one(self):
        self.login()
        first = self.issue()
        second = self.issue()
        self.assertNotEqual(first, second)
        self.assertContains(self.recover(first), 'Identifiant ou code de récupération incorrect')
        self.assertRedirects(self.recover(second), reverse('accounts:recovery_code') + '?premiere=1',
                             fetch_redirect_response=False)

    def test_code_page_requires_login_and_is_never_cached(self):
        self.assertEqual(Client().get(reverse('accounts:recovery_code')).status_code, 302)
        self.login()
        response = self.client.post(reverse('accounts:recovery_code'))
        self.assertIn('no-store', response['Cache-Control'])

    # --- Récupération -------------------------------------------------------
    def test_recover_sets_password_consumes_code_and_logs_out_other_devices(self):
        self.login()
        code = self.issue()
        other_device = self.client
        visitor = Client()
        response = self.recover(code.lower().replace('-', ' '), client=visitor)  # casse et séparateurs libres
        self.assertRedirects(response, reverse('accounts:recovery_code') + '?premiere=1',
                             fetch_redirect_response=False)
        self.student.refresh_from_db()
        self.assertTrue(self.student.check_password(NEW))
        self.assertEqual(self.student.recovery_code_hash, '')
        self.assertEqual(visitor.get(reverse('accounts:profile')).status_code, 200)  # connecté
        self.assertEqual(other_device.get(reverse('accounts:profile')).status_code, 302)  # déconnecté
        self.assertContains(self.recover(code, password='EncoreAutre2026!'),
                            'Identifiant ou code de récupération incorrect')

    def test_wrong_or_unknown_gets_the_same_error_and_attempts_are_limited(self):
        self.login()
        code = self.issue()
        self.assertContains(self.recover('AAAA-BBBB-CCCC'), 'Identifiant ou code de récupération incorrect')
        self.assertContains(self.recover(code, username='inconnu'), 'Identifiant ou code de récupération incorrect')
        for _ in range(MAX_FAILURES):
            self.recover('AAAA-BBBB-CCCC')
        self.assertContains(self.recover(code), 'Trop d’essais')
        self.student.refresh_from_db()
        self.assertTrue(self.student.check_password(PASSWORD))

    def test_invalid_new_password_keeps_code(self):
        self.login()
        code = self.issue()
        mismatch = Client().post(RECOVER, {'username': 'salma.b', 'code': code,
                                           'new_password1': NEW, 'new_password2': NEW + 'x'})
        self.assertContains(mismatch, 'ne correspondent pas')
        self.assertEqual(self.recover(code, password='salma.b').status_code, 200)
        self.student.refresh_from_db()
        self.assertTrue(self.student.recovery_code_hash)
        self.assertTrue(self.student.check_password(PASSWORD))

    def test_pending_or_disabled_account_cannot_recover(self):
        self.login()
        code = self.issue()
        User.objects.filter(pk=self.student.pk).update(is_active=False)
        self.assertContains(self.recover(code), 'Identifiant ou code de récupération incorrect')

    def test_forgot_page_offers_the_code_path(self):
        self.assertContains(Client().get(reverse('accounts:forgot_password')), RECOVER)

    # --- Changement volontaire ----------------------------------------------
    def test_voluntary_change_from_profile(self):
        self.login()
        self.issue()
        other = Client()
        self.login(other)
        page = self.client.get(reverse('accounts:change_password'))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'Mot de passe actuel')
        self.assertContains(self.client.get(reverse('accounts:profile')), reverse('accounts:change_password'))

        wrong = self.client.post(reverse('accounts:change_password'), {
            'old_password': 'faux', 'new_password1': NEW, 'new_password2': NEW})
        self.assertContains(wrong, 'Mot de passe actuel incorrect')

        done = self.client.post(reverse('accounts:change_password'), {
            'old_password': PASSWORD, 'new_password1': NEW, 'new_password2': NEW})
        self.assertRedirects(done, reverse('accounts:profile'), fetch_redirect_response=False)
        self.student.refresh_from_db()
        self.assertTrue(self.student.check_password(NEW))
        self.assertEqual(self.client.get(reverse('accounts:profile')).status_code, 200)
        self.assertEqual(other.get(reverse('accounts:profile')).status_code, 302)
