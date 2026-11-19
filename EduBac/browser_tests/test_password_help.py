"""Mot de passe oublié de bout en bout dans Chrome : demande depuis la connexion,
mot de passe provisoire créé par l'administrateur, nouveau mot de passe choisi
par l'élève. Vérifie aussi que les formulaires « sans cache » passent la
protection CSRF (en-tête Origin conservé).
"""
import os
import shutil

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from accounts.models import User

from .test_chat_moderation import PASSWORD, SingleThreadLiveServer

NEW_PASSWORD = 'NouveauSecret2026!'


class PasswordHelpBrowserTests(StaticLiveServerTestCase):
    server_thread_class = SingleThreadLiveServer

    def setUp(self):
        User.objects.create_superuser(username='prof-admin', email='prof-admin@example.test', password=PASSWORD)
        User.objects.create_user(username='salma.b', email='salma.b@example.test', password='Oublie123456!',
                                 first_name='Salma', last_name='Bennani', role='student')

    def login(self, page, username, password):
        page.goto(self.live_server_url + reverse('accounts:login'))
        page.locator('input[name="username"]').fill(username)
        page.locator('input[name="password"]').fill(password)
        page.locator('form button[type="submit"]').first.click()
        page.wait_for_url(lambda url: '/connexion/' not in url)

    def test_request_reset_and_choose_new_password(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                executable_path=os.environ.get('CHROMIUM_EXECUTABLE') or shutil.which('chromium'),
                headless=True, args=['--no-sandbox'])

            student = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True).new_page()
            student.goto(self.live_server_url + reverse('accounts:login'))
            student.get_by_role('link', name='Mot de passe oublié ?').click()
            student.fill('#helpName', 'Salma Bennani')
            student.fill('#helpClass', '1bac1')
            student.get_by_role('button', name='Envoyer la demande').click()
            expect(student.get_by_text('Demande envoyée.')).to_be_visible()

            admin = browser.new_context(viewport={'width': 1280, 'height': 900}).new_page()
            self.login(admin, 'prof-admin', PASSWORD)
            admin.goto(self.live_server_url + reverse('accounts:admin_dashboard'))
            requests = admin.locator('#password-requests')
            expect(requests).to_contain_text('1bac1')
            requests.get_by_role('link', name='Créer un mot de passe').click()
            admin.check('#identityVerified')
            admin.get_by_role('button', name='Réinitialiser le mot de passe').click()
            temporary = admin.locator('#temporaryPassword')
            expect(temporary).to_be_visible()
            password = temporary.input_value()
            admin.goto(self.live_server_url + reverse('accounts:admin_dashboard'))
            expect(admin.locator('#password-requests')).to_contain_text('Aucune demande de mot de passe en attente')

            self.login(student, 'salma.b', password)
            self.assertIn(reverse('accounts:change_password'), student.url)
            fields = student.locator('input[type="password"]')
            fields.nth(0).fill(NEW_PASSWORD)
            fields.nth(1).fill(NEW_PASSWORD)
            student.locator('form button[type="submit"]').first.click()
            student.wait_for_url(lambda url: reverse('accounts:change_password') not in url)
            self.assertNotIn('Accès refusé', student.content())

            fresh = browser.new_context().new_page()
            self.login(fresh, 'salma.b', NEW_PASSWORD)
            self.assertNotIn('/connexion/', fresh.url)
            browser.close()
