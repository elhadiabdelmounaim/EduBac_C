"""Application installable (PWA) dans Chrome : critères d'installation, service
worker, page hors connexion, cache limité aux ressources publiques, bouton
« Installer » (Android) et aide « Sur l'écran d'accueil » (iPhone).
"""
import os
import shutil
import tempfile

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from accounts.models import User
from classrooms.models import Classroom

from .test_chat_moderation import PASSWORD, SingleThreadLiveServer

IPHONE_UA = ('Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 '
             '(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1')


class ProgressiveWebAppBrowserTests(StaticLiveServerTestCase):
    server_thread_class = SingleThreadLiveServer

    def setUp(self):
        self.student = User.objects.create_user(
            username='pwa-eleve', email='pwa-eleve@example.test', password=PASSWORD,
            role='student', first_name='Yasmine', last_name='Bennani')
        teacher = User.objects.create_user(
            username='pwa-prof', email='pwa-prof@example.test', password=PASSWORD, role='teacher')
        Classroom.objects.create(name='TC', niveau='tronc_commun', teacher=teacher).add_member(self.student)

    def launch(self, pw):
        return pw.chromium.launch(
            executable_path=os.environ.get('CHROMIUM_EXECUTABLE') or shutil.which('chromium'),
            headless=True, args=['--no-sandbox'])

    def login(self, page):
        page.goto(self.live_server_url + reverse('accounts:login'))
        page.locator('input[name="username"]').fill(self.student.username)
        page.locator('input[name="password"]').fill(PASSWORD)
        page.locator('form button[type="submit"]').first.click()
        page.wait_for_url(lambda url: '/connexion/' not in url)

    def test_installable_offline_page_and_no_private_cache(self):
        with sync_playwright() as pw:
            # Profil réel (non privé) : Chrome n'installe jamais depuis une fenêtre privée.
            profile = tempfile.TemporaryDirectory()
            self.addCleanup(profile.cleanup)
            context = pw.chromium.launch_persistent_context(
                profile.name,
                executable_path=os.environ.get('CHROMIUM_EXECUTABLE') or shutil.which('chromium'),
                headless=True, args=['--no-sandbox'],
                viewport={'width': 412, 'height': 915}, is_mobile=True, has_touch=True)
            browser = context
            try:
                errors = []
                page = context.pages[0] if context.pages else context.new_page()
                page.on('pageerror', lambda error: errors.append(str(error)))
                self.login(page)
                page.wait_for_function('navigator.serviceWorker.ready.then(() => true)')
                page.reload()
                page.wait_for_function('!!navigator.serviceWorker.controller', timeout=10000)

                cdp = context.new_cdp_session(page)
                manifest = cdp.send('Page.getAppManifest')
                self.assertEqual(manifest.get('errors'), [], manifest.get('errors'))
                installability = cdp.send('Page.getInstallabilityErrors')
                self.assertEqual(installability['installabilityErrors'], [],
                                 'Chrome considère EduBac comme installable')

                # Pages privées visitées : cours, quiz, messagerie, notifications, tableau.
                for url in ('/', '/quizzes/assignes/', '/chat/', '/notifications/', '/tableau/'):
                    response = page.goto(self.live_server_url + url)
                    self.assertLess(response.status, 400, url)
                cached = page.evaluate("""async () => {
                    const urls = [];
                    for (const name of await caches.keys())
                        for (const request of await (await caches.open(name)).keys()) urls.push(new URL(request.url).pathname);
                    return urls;
                }""")
                self.assertIn('/hors-ligne/', cached)
                private = [url for url in cached if not (url.startswith('/static/') or url == '/hors-ligne/')]
                self.assertEqual(private, [], 'aucune page privée ni donnée personnelle en cache')

                context.set_offline(True)
                page.goto(self.live_server_url + '/quizzes/assignes/')
                expect(page.get_by_role('heading', name='Vous êtes hors connexion')).to_be_visible()
                self.assertNotIn('Yasmine', page.content())
                context.set_offline(False)
                page.goto(self.live_server_url + '/')
                expect(page.locator('.edubac-navbar')).to_be_visible()
                folder = os.environ.get('CHAT_SCREENSHOT_DIR')
                if folder:
                    context.set_offline(True)
                    page.goto(self.live_server_url + '/chat/')
                    page.screenshot(path=os.path.join(folder, 'pwa-offline.png'))
                    context.set_offline(False)
                self.assertEqual(errors, [])
            finally:
                browser.close()

    def test_android_install_button_uses_the_browser_prompt(self):
        with sync_playwright() as pw:
            browser = self.launch(pw)
            try:
                page = browser.new_page(viewport={'width': 412, 'height': 915})
                self.login(page)
                button = page.locator('.navbar-actions .dropdown-menu [data-pwa-install]').last
                expect(button).to_be_hidden()
                # Chrome envoie cet événement quand l'installation est possible.
                page.evaluate("""() => {
                    const event = new Event('beforeinstallprompt', { cancelable: true });
                    event.prompt = () => { window.__prompted = true; return Promise.resolve(); };
                    event.userChoice = Promise.resolve({ outcome: 'accepted' });
                    window.dispatchEvent(event);
                }""")
                page.locator('.navbar-actions [aria-label="Menu du compte"]').click()
                expect(button).to_be_visible()
                button.click()
                page.wait_for_function('window.__prompted === true')
            finally:
                browser.close()

    def test_iphone_gets_add_to_home_screen_instructions(self):
        with sync_playwright() as pw:
            browser = self.launch(pw)
            try:
                context = browser.new_context(
                    user_agent=IPHONE_UA, viewport={'width': 390, 'height': 844},
                    device_scale_factor=3, is_mobile=True, has_touch=True)
                page = context.new_page()
                # Invitation après quelques visites, jamais dès la première page.
                page.goto(self.live_server_url + '/')
                expect(page.locator('#pwaBanner')).to_be_hidden()
                page.reload()
                page.reload()
                banner = page.locator('#pwaBanner')
                expect(banner).to_be_visible()
                folder = os.environ.get('CHAT_SCREENSHOT_DIR')
                if folder:
                    page.screenshot(path=os.path.join(folder, 'pwa-banner-iphone.png'))
                banner.get_by_role('button', name='Installer').click()
                help_dialog = page.locator('#pwaHelp')
                expect(help_dialog).to_be_visible()
                expect(help_dialog.locator('#pwaHelpIos')).to_contain_text('Sur l’écran d’accueil')
                if folder:
                    page.screenshot(path=os.path.join(folder, 'pwa-help-iphone.png'))
                help_dialog.get_by_role('button', name='J’ai compris').click()
                page.reload()
                expect(page.locator('#pwaBanner')).to_be_hidden()
            finally:
                browser.close()
