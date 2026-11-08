"""Viewport checks for public forms, role-specific pages, and Django admin."""
import os
import shutil

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.urls import reverse
from playwright.sync_api import sync_playwright

from accounts.models import StudentProfile, TeacherProfile, User


VIEWPORTS = (320, 390, 480, 481, 600, 767, 768, 1024, 1440)


class ResponsiveLayoutBrowserTests(StaticLiveServerTestCase):
    def start_browser(self):
        self.playwright = sync_playwright().start()
        executable = os.environ.get("CHROMIUM_EXECUTABLE") or shutil.which("chromium")
        self.browser = self.playwright.chromium.launch(
            executable_path=executable,
            headless=True,
            args=["--no-sandbox"],
        )

    def tearDown(self):
        if hasattr(self, "browser"):
            self.browser.close()
            self.playwright.stop()
        super().tearDown()

    def assert_page_fits(self, page, route):
        response = page.goto(
            self.live_server_url + reverse(route),
            wait_until="domcontentloaded",
        )
        self.assertIsNotNone(response, f"{route} did not return a response")
        self.assertEqual(response.status, 200, f"{route} returned {response.status}")
        page.evaluate("document.fonts.ready")
        measurements = page.evaluate("""() => {
            const width = document.documentElement.clientWidth;
            const overflow = Math.max(
                document.documentElement.scrollWidth,
                document.body.scrollWidth
            );
            const outside = [...document.querySelectorAll(
                'input:not([type="hidden"]), select, textarea, button, a.btn'
            )].filter(element => {
                const style = getComputedStyle(element);
                const rect = element.getBoundingClientRect();
                const intersectsViewport = rect.right > 0 && rect.left < width &&
                    rect.bottom > 0 && rect.top < innerHeight;
                return style.display !== 'none' && style.visibility !== 'hidden' &&
                    intersectsViewport && element.getClientRects().length;
            }).map(element => {
                const rect = element.getBoundingClientRect();
                return rect.left < -1 || rect.right > width + 1
                    ? element.outerHTML
                    : null;
            }).filter(Boolean);
            const overflowers = [...document.querySelectorAll('body *')]
                .filter(element => {
                    const rect = element.getBoundingClientRect();
                    return rect.width > 0 && rect.right > width + 1 && rect.left < width;
                })
                .slice(0, 10)
                .map(element => ({
                    tag: element.tagName,
                    id: element.id,
                    className: typeof element.className === 'string' ? element.className : '',
                    text: (element.innerText || '').slice(0, 80),
                    left: Math.round(element.getBoundingClientRect().left),
                    right: Math.round(element.getBoundingClientRect().right)
                }));
            return {width, overflow, outside, overflowers};
        }""")
        self.assertLessEqual(
            measurements["overflow"],
            measurements["width"] + 1,
            f"{route} has document overflow at {measurements['width']}px: "
            f"{measurements['overflowers']}",
        )
        self.assertEqual(
            measurements["outside"],
            [],
            f"{route} has controls outside the viewport: {measurements['outside']}",
        )

    def test_guest_forms_and_public_pages_fit_target_widths(self):
        self.start_browser()
        context = self.browser.new_context()
        try:
            page = context.new_page()
            routes = (
                "education:home",
                "education:about",
                "accounts:login",
                "accounts:register_choice",
                "accounts:register_student",
                "accounts:register_teacher",
            )
            for width in VIEWPORTS:
                page.set_viewport_size({"width": width, "height": 900})
                for route in routes:
                    with self.subTest(width=width, route=route):
                        self.assert_page_fits(page, route)
        finally:
            context.close()

    def test_student_and_teacher_pages_fit_target_widths(self):
        role_cases = (
            (
                "student",
                StudentProfile,
                ("accounts:dashboard", "accounts:profile", "classrooms:join", "quizzes:assigned"),
            ),
            (
                "teacher",
                TeacherProfile,
                (
                    "accounts:dashboard",
                    "accounts:profile",
                    "classrooms:create",
                    "quizzes:create",
                    "quizzes:manage",
                    "ai:assistant",
                ),
            ),
        )
        users = {}
        for role, profile_model, _routes in role_cases:
            users[role] = User.objects.create_user(
                username=f"responsive_{role}",
                email=f"responsive_{role}@example.test",
                password="Browser-test-only-123!",
                role=role,
                first_name="Samira",
                last_name="Test",
            )
            profile_model.objects.get_or_create(user=users[role])

        self.start_browser()
        for role, _profile_model, routes in role_cases:
            user = users[role]
            context = self.browser.new_context()
            try:
                page = context.new_page()
                page.set_viewport_size({"width": 390, "height": 900})
                page.goto(
                    self.live_server_url + reverse("accounts:login"),
                    wait_until="domcontentloaded",
                )
                page.locator('input[name="email"]').fill(user.email)
                page.locator('input[name="password"]').fill("Browser-test-only-123!")
                page.locator('button[type="submit"]').click()
                page.wait_for_url(lambda url: "/connexion/" not in url)

                for width in VIEWPORTS:
                    page.set_viewport_size({"width": width, "height": 900})
                    for route in routes:
                        with self.subTest(role=role, width=width, route=route):
                            self.assert_page_fits(page, route)
            finally:
                context.close()

    def test_django_admin_pages_fit_target_widths(self):
        User.objects.create_superuser(
            username="responsive_admin",
            email="responsive_admin@example.test",
            password="Browser-test-only-123!",
        )
        self.start_browser()
        context = self.browser.new_context()
        try:
            page = context.new_page()
            page.set_viewport_size({"width": 390, "height": 900})
            page.goto(self.live_server_url + "/admin/login/", wait_until="domcontentloaded")
            page.locator('input[name="username"]').fill("responsive_admin")
            page.locator('input[name="password"]').fill("Browser-test-only-123!")
            page.locator('input[type="submit"]').click()
            page.wait_for_url(lambda url: "/admin/" in url and "login" not in url)
            for width in VIEWPORTS:
                page.set_viewport_size({"width": width, "height": 900})
                with self.subTest(width=width):
                    self.assert_page_fits(page, "admin:index")
        finally:
            context.close()
