"""Real HTTP + Chromium regression checks, with no injected auth or HTML fixtures."""
import os
from pathlib import Path
import shutil

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from accounts.models import User, StudentProfile, TeacherProfile


WIDTHS = (360, 375, 390, 414, 430, 768, 1024, 1440)
NAV = ".edubac-navbar"


class NavbarBrowserTests(StaticLiveServerTestCase):
    def start_browser(self):
        self.pw = sync_playwright().start()
        self.addCleanup(self.pw.stop)
        executable = os.environ.get("CHROMIUM_EXECUTABLE") or shutil.which("chromium")
        self.browser = self.pw.chromium.launch(
            executable_path=executable, headless=True, args=["--no-sandbox"]
        )
        self.addCleanup(self.browser.close)

    def tab_to(self, page, target):
        """Use actual sequential keyboard navigation, not element.focus()."""
        for _ in range(90):
            page.keyboard.press("Tab")
            if target.evaluate("(el) => el === document.activeElement"):
                expect(target).to_be_visible()
                return
        self.fail(f"Not reachable by Tab: {target}")

    def load(self, page, route):
        response = page.goto(self.live_server_url + reverse(route))
        self.assertEqual(response.status, 200)
        page.wait_for_function("typeof bootstrap !== 'undefined'")
        page.evaluate("document.fonts.ready")
        # Do not suppress motion to make assertions pass. Allow entrance animations.
        page.wait_for_timeout(700)

    def geometry(self, page):
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(200)
        issues = page.evaluate("""() => {
            const errors = [], nav = document.querySelector('.edubac-navbar');
            const h = nav.getBoundingClientRect(), eps = 1;
            const visible = e => e.getClientRects().length &&
                getComputedStyle(e).visibility !== 'hidden';
            const controls = [...nav.querySelectorAll('a,button,input')]
                .filter(e => visible(e) && !e.closest('.dropdown-menu'));
            for (const e of controls) {
                const r = e.getBoundingClientRect();
                if (r.left < h.left-eps || r.right > h.right+eps ||
                    r.top < h.top-eps || r.bottom > h.bottom+eps)
                    errors.push('Control outside header: '+e.outerHTML);
            }
            for (let i=0; i<controls.length; i++) {
                for (let j=i+1; j<controls.length; j++) {
                    const a=controls[i].getBoundingClientRect();
                    const b=controls[j].getBoundingClientRect();
                    if (Math.min(a.right,b.right)-Math.max(a.left,b.left)>eps &&
                        Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top)>eps)
                        errors.push('Overlapping controls: '+controls[i].outerHTML+
                            ' / '+controls[j].outerHTML);
                }
            }
            for (const selector of ['.edubac-layout', 'main']) {
                if (document.querySelector(selector).getBoundingClientRect().top < h.bottom-eps)
                    errors.push(selector+' starts behind header');
            }
            if (document.documentElement.scrollWidth > innerWidth+eps ||
                document.body.scrollWidth > innerWidth+eps)
                errors.push('Horizontal overflow');
            for (const menu of nav.querySelectorAll('.dropdown-menu.show')) {
                const r=menu.getBoundingClientRect();
                if (r.left < -eps || r.right > innerWidth+eps ||
                    r.top < -eps || r.bottom > innerHeight+eps)
                    errors.push('Open menu clipped by viewport');
            }
            return errors;
        }""")
        self.assertEqual(issues, [], "\n".join(issues))

    def menu(self, page, label, destinations):
        trigger = page.locator(NAV).get_by_role("button", name=label, exact=True)
        self.tab_to(page, trigger)
        page.keyboard.press("Enter")
        expect(trigger).to_have_attribute("aria-expanded", "true")
        menu = page.locator(f"{NAV} .dropdown-menu.show")
        expect(menu).to_be_visible()
        self.geometry(page)
        links = menu.locator("a")
        self.assertEqual(links.count(), len(destinations))
        for index, destination in enumerate(destinations):
            page.keyboard.press("ArrowDown")
            expect(links.nth(index)).to_be_focused()
            expect(links.nth(index)).to_have_attribute("href", reverse(destination))
        page.keyboard.press("Escape")
        expect(menu).to_have_count(0)
        expect(trigger).to_be_focused()
        expect(trigger).to_have_attribute("aria-expanded", "false")

    def run_matrix(self, role):
        user = None
        if role != "guest":
            user = User.objects.create_user(
                username=f"navbar_{role}", email=f"navbar_{role}@example.test",
                password="Browser-test-only-123!", role=role,
                first_name="Alexandre", last_name="Benali",
            )
            profile = StudentProfile if role == "student" else TeacherProfile
            profile.objects.get_or_create(user=user)
        self.start_browser()
        for width in WIDTHS:
            with self.subTest(role=role, width=width):
                context = self.browser.new_context(
                    viewport={"width": width, "height": 900}, reduced_motion="no-preference"
                )
                page = context.new_page()
                page.set_default_timeout(10000)
                try:
                    if user:
                        self.load(page, "accounts:login")
                        page.locator('input[name="email"]').fill(user.email)
                        page.locator('input[name="password"]').fill("Browser-test-only-123!")
                        page.get_by_role("button", name="Se connecter", exact=True).click()
                        page.wait_for_url(lambda url: "/connexion/" not in url)
                        # Reload through real middleware and prove a protected API accepts the cookie.
                        page.reload()
                        response = context.request.get(
                            self.live_server_url + reverse("notifications:api_count")
                        )
                        self.assertEqual(response.status, 200)
                        self.assertIn("unread_count", response.json())
                        self.assertTrue(any(c["name"] == "sessionid" for c in context.cookies()))
                    self.load(page, "education:about")
                    nav = page.locator(NAV)
                    self.geometry(page)
                    self.tab_to(page, nav.locator("#themeToggle"))
                    page.keyboard.press("Enter")
                    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
                    self.geometry(page)
                    page.reload()
                    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
                    self.tab_to(page, nav.locator("#themeToggle"))
                    page.keyboard.press("Space")
                    expect(page.locator("html")).not_to_have_attribute("data-theme", "dark")
                    destinations = ["education:home", "whiteboard:list", "education:about"]
                    if width < 992:
                        self.menu(page, "Menu pages", destinations)
                    else:
                        for dest in destinations:
                            link = nav.locator(f'a.nav-link[href="{reverse(dest)}"]')
                            self.tab_to(page, link)
                    if user:
                        self.menu(page, "Menu du compte", [
                            "accounts:profile", "accounts:profile", "accounts:logout",
                        ])
                        bell = nav.locator("#notifBellBtn")
                        self.tab_to(page, bell)
                        page.keyboard.press("Enter")
                        expect(bell).to_have_attribute("aria-expanded", "true")
                        self.geometry(page)
                        self.tab_to(page, nav.locator("#notifMarkAllRead"))
                        with page.expect_response(
                            lambda r: r.url.endswith(reverse("notifications:api_mark_all_read"))
                            and r.request.method == "POST"
                        ) as marked:
                            page.keyboard.press("Enter")
                        self.assertEqual(marked.value.status, 200)
                        page.keyboard.press("Escape")
                        expect(bell).to_be_focused()
                        expect(bell).to_have_attribute("aria-expanded", "false")
                        # Activate logout from the actual account menu.
                        self.menu(page, "Menu du compte", [
                            "accounts:profile", "accounts:profile", "accounts:logout",
                        ])
                        page.keyboard.press("Enter")
                        logout = nav.locator(f'a[href="{reverse("accounts:logout")}"]')
                        self.tab_to(page, logout)
                        page.keyboard.press("Enter")
                        expect(nav.get_by_role("link", name="Connexion", exact=True)).to_be_visible()
                    else:
                        for name, dest in [("Inscription", "accounts:register_choice"),
                                           ("Connexion", "accounts:login")]:
                            link = nav.get_by_role("link", name=name, exact=True)
                            expect(link).to_have_attribute("href", reverse(dest))
                            self.tab_to(page, link)
                            page.keyboard.press("Enter")
                            landing = "accounts:register_student" if name == "Inscription" else dest
                            page.wait_for_url(self.live_server_url + reverse(landing))
                            page.wait_for_timeout(700)
                            self.geometry(page)
                            self.load(page, "education:about")
                except Exception:
                    output = Path("test-results/navbar")
                    output.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(output / f"{role}-{width}.png"), full_page=True)
                    raise
                finally:
                    context.close()

    def test_guest(self):
        self.run_matrix("guest")

    def test_student(self):
        self.run_matrix("student")

    def test_teacher(self):
        self.run_matrix("teacher")
