"""Real-browser coverage for username signup and administrator approval."""
import os
import shutil

from accounts.models import User
from classrooms.models import Classroom
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.cache import cache
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright


class StudentApprovalBrowserTests(StaticLiveServerTestCase):
    def setUp(self):
        cache.clear()
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

    def test_signup_waits_for_admin_approval_before_login(self):
        administrator = User.objects.create_user(
            username='browser-admin',
            email='browser-admin@example.test',
            password='BrowserAdmin-2026!',
            role='teacher',
            is_staff=True,
            is_superuser=True,
        )
        Classroom.objects.create(
            name='Classe navigateur',
            niveau='tronc_commun',
            code='BROWSER26',
            teacher=administrator,
        )
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
            page.locator('input[name="username"]').fill('browser_student')
            page.locator('input[name="class_code"]').fill('BROWSER26')
            page.locator('input[name="password"]').fill('BrowserTest-2026!')
            page.locator('input[name="password2"]').fill('BrowserTest-2026!')
            page.locator('button[type="submit"]').click()

            page.wait_for_url(f'**{reverse("accounts:login")}')
            expect(page.get_by_text('Votre demande a été envoyée.')).to_be_visible()
            expect(page.locator('input[name="email"]')).to_have_count(0)
            for width in (320, 390, 768, 1440):
                self.assert_page_fits(page, width)

            page.locator('input[name="username"]').fill('browser_student')
            page.locator('input[name="password"]').fill('BrowserTest-2026!')
            page.locator('button[type="submit"]').click()
            expect(
                page.get_by_text(
                    'Votre demande d’inscription attend la validation de l’administrateur.'
                )
            ).to_be_visible()

            page.goto(
                self.live_server_url + reverse('accounts:logout'),
                wait_until='domcontentloaded',
            )
            page.goto(
                self.live_server_url + reverse('accounts:login'),
                wait_until='domcontentloaded',
            )
            page.locator('input[name="username"]').fill('browser-admin')
            page.locator('input[name="password"]').fill('BrowserAdmin-2026!')
            page.locator('button[type="submit"]').click()
            page.wait_for_url(f'**{reverse("accounts:admin_dashboard")}')
            page.get_by_role('button', name='Accepter').click()
            expect(page.get_by_text('Aucune demande d’inscription en attente.')).to_be_visible()

            page.goto(
                self.live_server_url + reverse('accounts:logout'),
                wait_until='domcontentloaded',
            )
            page.goto(
                self.live_server_url + reverse('accounts:login'),
                wait_until='domcontentloaded',
            )
            page.locator('input[name="username"]').fill('browser_student')
            page.locator('input[name="password"]').fill('BrowserTest-2026!')
            page.locator('button[type="submit"]').click()
            page.wait_for_url(f'**{reverse("accounts:dashboard")}')
            expect(page).to_have_url(self.live_server_url + reverse('accounts:dashboard'))
        finally:
            context.close()
