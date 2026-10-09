from playwright.sync_api import expect
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.urls import reverse
from accounts.models import User, TeacherProfile
from notifications.models import Notification
from . import test_navbar


class NotificationBrowserTests(StaticLiveServerTestCase):
    start_browser = test_navbar.NavbarBrowserTests.start_browser
    def test_unread_list_and_badge(self):
        user = User.objects.create_user(
            username="notification_teacher", email="notify@example.test",
            password="Browser-test-only-123!", role="teacher",
        )
        TeacherProfile.objects.get_or_create(user=user)
        Notification.objects.bulk_create([
            Notification(recipient=user, title=f"Notification {i}", message="Test", link="")
            for i in range(12)
        ])
        self.start_browser()
        context = self.browser.new_context(viewport={"width": 390, "height": 844})
        self.addCleanup(context.close)
        page = context.new_page()
        page.goto(self.live_server_url + reverse("accounts:login"))
        page.locator('[name="email"]').fill(user.email)
        page.locator('[name="password"]').fill("Browser-test-only-123!")
        page.get_by_role("button", name="Se connecter", exact=True).click()
        page.wait_for_url(lambda url: "/connexion/" not in url)
        badge = page.locator("#notifBadge")
        expect(badge).to_have_text("12")
        expect(badge).to_be_visible()
        self.assertGreaterEqual(badge.bounding_box()["width"], 22)
        page.locator("#notifBellBtn").click()
        expect(page.locator(".notif-item")).to_have_count(12)
        self.assertEqual(page.locator("#notifMarkAllRead").evaluate(
            "(el) => getComputedStyle(el).color"
        ), "rgb(21, 94, 99)")
        page.screenshot(path="/tmp/notification-mobile.jpg")
        page.set_viewport_size({"width": 1280, "height": 850})
        expect(badge).to_be_visible()
        page.screenshot(path="/tmp/notification-desktop.jpg")
        page.locator(".notif-item").first.click()
        expect(page.locator(".notif-item")).to_have_count(11)
        expect(badge).to_have_text("11")
        mark_all = "**" + reverse("notifications:api_mark_all_read")
        page.route(mark_all, lambda route: route.fulfill(
            status=500, content_type="application/json", body='{"error":"Test failure"}',
        ))
        page.locator("#notifMarkAllRead").click()
        expect(page.locator("#notifError")).to_be_visible()
        expect(page.locator(".notif-item")).to_have_count(11)
        expect(badge).to_have_text("11")
        page.unroute(mark_all)
        page.locator("#notifMarkAllRead").click()
        expect(page.locator(".notif-item")).to_have_count(0)
        expect(badge).to_be_hidden()
        page.reload()
        page.locator("#notifBellBtn").click()
        expect(page.locator(".notif-item")).to_have_count(0)
        expect(badge).to_be_hidden()
