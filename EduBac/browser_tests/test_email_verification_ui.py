"""Real-browser coverage for the email-verification signup journey."""
import os
import re
import shutil

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core import mail
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright


@override_settings(
    ALLOWED_HOSTS=['localhost', '127.0.0.1', 'testserver'],
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
)
class EmailVerificationBrowserTests(StaticLiveServerTestCase):
    def setUp(self):
        cache.clear()
        mail.outbox.clear()
        self.playwright = None
        self.browser = None

    def tearDown(self):
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()
        super().tearDown()

    def assert_page_fits(self, page, width):
        page.set_viewport_size({'width': width, 'height': 900})
        result = page.evaluate("""() => {
            const width = document.documentElement.clientWidth;
            const controls = [...document.querySelectorAll(
                'input:not([type="hidden"]), button'
            )].filter(element => element.getClientRects().length);
            return {
                width,
                scrollWidth: document.documentElement.scrollWidth,
                outside: controls.some(element => {
                    const rect = element.getBoundingClientRect();
                    return rect.left < -1 || rect.right > width + 1;
                })
            };
        }""")
        self.assertLessEqual(
            result['scrollWidth'],
            width + 1,
            f"Document overflow at {width}px",
        )
        self.assertFalse(result['outside'], f"Control outside viewport at {width}px")

    def test_signup_pending_confirmation_and_login(self):
        self.playwright = sync_playwright().start()
        executable = os.environ.get('CHROMIUM_EXECUTABLE') or shutil.which('chromium')
        self.browser = self.playwright.chromium.launch(
            executable_path=executable,
            headless=True,
            args=['--no-sandbox'],
        )
        context = self.browser.new_context(viewport={'width': 390, 'height': 900})
        page = context.new_page()
        try:
            page.goto(
                self.live_server_url + reverse('accounts:register_student'),
                wait_until='domcontentloaded',
            )
            page.locator('input[name="name"]').fill('Test Verification')
            page.locator('input[name="email"]').fill('browser-verify@example.test')
            page.locator('input[name="password"]').fill('BrowserTest-2026!')
            page.locator('input[name="password2"]').fill('BrowserTest-2026!')
            page.locator('button[type="submit"]').click()

            page.wait_for_url(f'**{reverse("accounts:email_verification_pending")}')
            expect(page.get_by_role('heading', name='Vérifie ta boîte mail')).to_be_visible()
            expect(
                page.get_by_text('browser-verify@example.test', exact=True)
            ).to_be_visible()
            expect(
                page.get_by_role('button', name='Renvoyer le lien de vérification')
            ).to_be_visible()
            for width in (320, 390, 768, 1440):
                self.assert_page_fits(page, width)

            page.goto(
                self.live_server_url + reverse('accounts:login'),
                wait_until='domcontentloaded',
            )
            page.locator('input[name="email"]').fill('browser-verify@example.test')
            page.locator('input[name="password"]').fill('BrowserTest-2026!')
            page.locator('button[type="submit"]').click()
            page.wait_for_url(f'**{reverse("accounts:email_verification_pending")}')
            expect(page.get_by_role('heading', name='Vérifie ta boîte mail')).to_be_visible()

            self.assertEqual(len(mail.outbox), 1)
            link = re.search(
                r'(?:https?://[^/\s]+)?(/compte/verification-email/confirmer/[^\s]+)',
                mail.outbox[0].body,
            )
            self.assertIsNotNone(link, 'Verification email did not contain a confirm link.')
            confirm_path = link.group(1).rstrip('/')
            page.goto(self.live_server_url + confirm_path, wait_until='domcontentloaded')
            expect(page.get_by_role('heading', name='Adresse e-mail vérifiée')).to_be_visible()

            page.goto(
                self.live_server_url + reverse('accounts:login'),
                wait_until='domcontentloaded',
            )
            page.locator('input[name="email"]').fill('browser-verify@example.test')
            page.locator('input[name="password"]').fill('BrowserTest-2026!')
            page.locator('button[type="submit"]').click()
            page.wait_for_url(f'**{reverse("accounts:dashboard")}')
            expect(page).to_have_url(self.live_server_url + reverse('accounts:dashboard'))
        finally:
            context.close()
