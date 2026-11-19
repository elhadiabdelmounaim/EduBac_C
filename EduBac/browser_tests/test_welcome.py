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
                page.wait_for_selector('#appSplash', state='detached', timeout=12000)
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


    def test_splash_loads_shared_files_then_reveals_welcome_once(self):
        with sync_playwright() as pw:
            browser = self.launch(pw)
            context = self.phone(browser)
            page = context.new_page()
            static_requests = []
            page.on('request', lambda r: static_requests.append(r.url) if '/static/' in r.url else None)
            page.goto(self.live_server_url + reverse('education:welcome'))
            splash = page.locator('#appSplash')
            self.assertTrue(splash.is_visible())
            page.wait_for_timeout(5500)
            self.assertTrue(splash.is_visible(), "l'écran de chargement reste 6 secondes")
            if SHOTS:
                page.wait_for_timeout(700)
                page.screenshot(path=os.path.join(SHOTS, 'splash.png'))
            # Le bouton est recouvert tant que le chargement n'est pas fini.
            self.assertFalse(page.evaluate(
                "document.elementFromPoint(innerWidth / 2, innerHeight - 140).closest('.welcome-start') !== null"
                " && !document.getElementById('appSplash')"))
            page.wait_for_selector('#appSplash', state='detached', timeout=12000)
            self.assertTrue(any('bootstrap.bundle.min.js' in url for url in static_requests))
            self.assertTrue(any('bootstrap-icons.woff2' in url for url in static_requests))
            page.get_by_role('link', name='Commencer').wait_for()
            # Retour sur l'accueil dans la même session : pas de nouvel écran de chargement.
            page.reload()
            self.assertEqual(page.locator('#appSplash').count(), 0)
            context.close()
            browser.close()

    def test_splash_never_blocks_on_slow_or_missing_network(self):
        with sync_playwright() as pw:
            browser = self.launch(pw)
            # Réseau très lent : message adapté, puis accueil au plus tard après 9 s.
            context = self.phone(browser)
            page = context.new_page()
            cdp = context.new_cdp_session(page)
            cdp.send('Network.enable')
            cdp.send('Network.emulateNetworkConditions', {
                'offline': False, 'latency': 1500, 'downloadThroughput': 25000, 'uploadThroughput': 25000})
            page.goto(self.live_server_url + reverse('education:welcome'), wait_until='commit')
            page.wait_for_selector('#appSplash', state='visible', timeout=25000)
            page.wait_for_function(
                "document.getElementById('appSplashStatus')?.textContent.includes('Connexion lente')", timeout=25000)
            page.wait_for_selector('#appSplash', state='detached', timeout=25000)
            # Jamais de page brute : la mise en page de l'accueil est appliquée.
            self.assertEqual(page.evaluate("getComputedStyle(document.querySelector('.welcome')).display"), 'flex')
            context.close()

            # Fichiers inaccessibles : l'accueil s'affiche quand même.
            context = self.phone(browser)
            page = context.new_page()
            page.route('**/static/vendor/**', lambda route: route.abort())
            page.goto(self.live_server_url + reverse('education:welcome'))
            page.wait_for_selector('#appSplash', state='detached', timeout=12000)
            context.close()
            browser.close()
