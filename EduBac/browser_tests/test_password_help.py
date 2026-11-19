"""Mot de passe oublié de bout en bout dans Chrome : demande depuis la connexion,
mot de passe provisoire créé par l'administrateur, nouveau mot de passe choisi
par l'élève. Vérifie aussi que les formulaires « sans cache » passent la
protection CSRF (en-tête Origin conservé).
"""
import os
import re
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

    def test_student_recovers_alone_with_code_and_changes_password_from_profile(self):
        shots = os.environ.get('RECOVERY_SHOTS')
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                executable_path=os.environ.get('CHROMIUM_EXECUTABLE') or shutil.which('chromium'),
                headless=True, args=['--no-sandbox'])
            page = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True).new_page()

            # Première connexion : le code est proposé puis affiché une fois.
            self.login(page, 'salma.b', 'Oublie123456!')
            self.assertIn(reverse('accounts:recovery_code'), page.url)
            page.get_by_role('button', name='Afficher mon code').click()
            code = page.locator('#recoveryCode').inner_text().strip()
            self.assertRegex(code, r'^[A-Z2-9]{4}-[A-Z2-9]{4}-[A-Z2-9]{4}$')
            if shots:
                page.screenshot(path=os.path.join(shots, 'code.png'), full_page=True)
            page.get_by_role('link', name='J’ai noté mon code — continuer').click()
            page.wait_for_url('**' + reverse('accounts:dashboard'))

            # Changement volontaire depuis le profil.
            page.goto(self.live_server_url + reverse('accounts:profile'))
            page.get_by_role('link', name='Changer mon mot de passe').click()
            page.fill('#id_old_password', 'Oublie123456!')
            page.fill('#id_new_password1', NEW_PASSWORD)
            page.fill('#id_new_password2', NEW_PASSWORD)
            page.get_by_role('button', name='Enregistrer le nouveau mot de passe').click()
            page.wait_for_url('**' + reverse('accounts:profile'))
            expect(page.get_by_text('Votre mot de passe a été modifié.')).to_be_visible()

            # Mot de passe oublié : l'élève se débrouille seul avec son code.
            page.goto(self.live_server_url + reverse('accounts:logout'))
            page.goto(self.live_server_url + reverse('accounts:login'))
            page.get_by_role('link', name='Mot de passe oublié ?').click()
            if shots:
                page.wait_for_timeout(1200)
                page.screenshot(path=os.path.join(shots, 'forgot.png'), full_page=True)
            page.get_by_role('link', name=re.compile('J’ai mon code de récupération')).click()
            page.fill('#id_username', 'salma.b')
            page.fill('#id_code', code.lower())
            page.fill('#id_new_password1', 'TroisiemeSecret2026!')
            page.fill('#id_new_password2', 'TroisiemeSecret2026!')
            if shots:
                page.screenshot(path=os.path.join(shots, 'recover.png'), full_page=True)
            page.get_by_role('button', name='Changer mon mot de passe').click()
            page.wait_for_url('**' + reverse('accounts:recovery_code') + '?premiere=1')
            page.get_by_role('button', name='Afficher mon code').click()
            self.assertNotEqual(page.locator('#recoveryCode').inner_text().strip(), code)

            fresh = browser.new_context().new_page()
            self.login(fresh, 'salma.b', 'TroisiemeSecret2026!')
            self.assertNotIn('/connexion/', fresh.url)
            browser.close()
