"""Écran d'accueil mobile : rendu sur plusieurs smartphones, passage unique par
session depuis l'accueil, bureau inchangé, bouton « Commencer » selon la session.
"""
import os
import shutil

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.urls import reverse
from playwright.sync_api import sync_playwright

from accounts.models import User

from .test_chat_moderation import PASSWORD, SingleThreadLiveServer

PHONES = ((320, 568), (360, 640), (390, 844), (430, 932))
# Playwright signale navigator.webdriver ; le vrai téléphone ne le fait pas.
REAL_PHONE = "Object.defineProperty(Navigator.prototype, 'webdriver', {get: () => false});"
SHOTS = os.environ.get('WELCOME_SHOTS')


class WelcomeScreenBrowserTests(StaticLiveServerTestCase):
    server_thread_class = SingleThreadLiveServer

    def setUp(self):
        self.student = User.objects.create_user(
            username='bienvenue-eleve', email='bienvenue-eleve@example.test',
            password=PASSWORD, role='student')

    def launch(self, pw):
        return pw.chromium.launch(
            executable_path=os.environ.get('CHROMIUM_EXECUTABLE') or shutil.which('chromium'),
            headless=True, args=['--no-sandbox'])

    def phone(self, browser, width=390, height=844):
        context = browser.new_context(viewport={'width': width, 'height': height},
                                      device_scale_factor=2, is_mobile=True, has_touch=True)
        context.add_init_script(REAL_PHONE)
        return context

    def test_renders_on_phones_without_overflow(self):
        with sync_playwright() as pw:
            browser = self.launch(pw)
            for width, height in PHONES:
                context = self.phone(browser, width, height)
                page = context.new_page()
                page.goto(self.live_server_url + reverse('education:welcome'))
                page.wait_for_function("[...document.images].every(i => i.complete && i.naturalWidth > 0)")
                page.wait_for_timeout(900)  # fin des animations d'entrée
                m = page.evaluate("""() => {
                    const r = s => document.querySelector(s).getBoundingClientRect();
                    return {scroll: document.documentElement.scrollWidth, width: innerWidth,
                            start: r('.welcome-start'), cards: r('.welcome-features'),
                            ill: r('.welcome-illustration img'), h: innerHeight};
                }""")
                self.assertLessEqual(m['scroll'], m['width'], f'{width}px : défilement horizontal')
                self.assertGreater(m['ill']['height'], 60, f'{width}px : illustration écrasée')
                self.assertLessEqual(m['cards']['right'], width)
                if height >= 640:
                    self.assertLessEqual(m['start']['bottom'], m['h'], f'{width}x{height} : bouton hors écran')
                if SHOTS:
                    page.screenshot(path=os.path.join(SHOTS, f'welcome-{width}x{height}.png'), full_page=True)
                context.close()
            browser.close()

    def test_home_shows_welcome_once_per_session_on_phone_only(self):
        home = self.live_server_url + reverse('education:home')
        welcome = self.live_server_url + reverse('education:welcome')
        with sync_playwright() as pw:
            browser = self.launch(pw)
            context = self.phone(browser)
            page = context.new_page()
            page.goto(home)
            page.wait_for_url(welcome)
            page.goto(home)  # navigation interne : plus de passage par l'écran
            page.wait_for_timeout(300)
            self.assertEqual(page.url, home)
            context.close()

            desktop = browser.new_context(viewport={'width': 1366, 'height': 800})
            desktop.add_init_script(REAL_PHONE)
            page = desktop.new_page()
            page.goto(home)
            page.wait_for_timeout(300)
            self.assertEqual(page.url, home)
            desktop.close()
            browser.close()

    def test_start_button_follows_session(self):
        with sync_playwright() as pw:
            browser = self.launch(pw)
            context = self.phone(browser)
            page = context.new_page()
            page.goto(self.live_server_url + reverse('education:welcome'))
            page.get_by_role('link', name='Commencer').click()
            page.wait_for_url('**' + reverse('accounts:login'))
            page.locator('input[name="username"]').fill(self.student.username)
            page.locator('input[name="password"]').fill(PASSWORD)
            page.locator('form button[type="submit"]').first.click()
            page.wait_for_url(lambda url: '/connexion/' not in url)
            page.goto(self.live_server_url + reverse('education:welcome'))
            page.get_by_role('link', name='Commencer').click()
            page.wait_for_url('**' + reverse('accounts:dashboard'))
            context.close()
            browser.close()
