"""Notifications sur le téléphone : réception par le service worker dans Chrome.

Chrome DevTools injecte un message push comme le ferait le service de Google ;
on vérifie que la notification s'affiche avec le bon titre, et le bouton d'activation.
"""
import json
import os
import shutil
import tempfile

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from accounts.models import User
from notifications.push import generate_vapid_keys

from .test_chat_moderation import PASSWORD, SingleThreadLiveServer

PUBLIC, PRIVATE = generate_vapid_keys()
LIST = """async () => (await (await navigator.serviceWorker.ready).getNotifications())
    .map(n => [n.title, n.body, n.tag, n.data.url])"""


def wait_notifications(page, predicate, attempts=40):
    for _ in range(attempts):
        shown = page.evaluate(LIST)
        if predicate(shown):
            return shown
        page.wait_for_timeout(250)
    return page.evaluate(LIST)


@override_settings(WEBPUSH_VAPID_PUBLIC_KEY=PUBLIC, WEBPUSH_VAPID_PRIVATE_KEY=PRIVATE)
class PushNotificationBrowserTests(StaticLiveServerTestCase):
    server_thread_class = SingleThreadLiveServer

    def setUp(self):
        User.objects.create_user(username='push-eleve', email='push@example.test', password=PASSWORD,
                                 role='student', first_name='Omar')

    def test_service_worker_shows_the_pushed_message_and_opens_the_page(self):
        profile = tempfile.TemporaryDirectory()
        self.addCleanup(profile.cleanup)
        with sync_playwright() as pw:
            context = pw.chromium.launch_persistent_context(
                profile.name, executable_path=os.environ.get('CHROMIUM_EXECUTABLE') or shutil.which('chromium'),
                headless=True, args=['--no-sandbox'], viewport={'width': 412, 'height': 900})
            try:
                context.grant_permissions(['notifications'], origin=self.live_server_url)
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(self.live_server_url + reverse('accounts:login'))
                page.locator('[name="username"]').fill('push-eleve')
                page.locator('[name="password"]').fill(PASSWORD)
                page.locator('form button[type="submit"]').first.click()
                page.wait_for_url(lambda url: '/connexion/' not in url)
                page.goto(self.live_server_url + reverse('notifications:preferences'))
                page.wait_for_function('navigator.serviceWorker.ready.then(() => true)')
                # Le bouton d'activation est proposé (clés configurées).
                expect(page.locator('.push-pref [data-push-toggle]')).to_be_visible()

                cdp = context.new_cdp_session(page)
                registrations = []
                cdp.on('ServiceWorker.workerRegistrationUpdated', lambda e: registrations.extend(e['registrations']))
                cdp.send('ServiceWorker.enable')
                page.wait_for_timeout(500)
                registration_id = next(r['registrationId'] for r in registrations if not r.get('isDeleted'))
                payload = {'title': 'Consultation — nouveau message', 'body': 'Nadia : Révisez la page 12.',
                           'url': '/chat/', 'tag': 'conversation-1'}
                cdp.send('ServiceWorker.deliverPushMessage', {
                    'origin': self.live_server_url, 'registrationId': registration_id, 'data': json.dumps(payload)})
                shown = wait_notifications(page, bool)
                self.assertEqual(shown, [['Consultation — nouveau message', 'Nadia : Révisez la page 12.',
                                          'conversation-1', '/chat/']])
                # Un deuxième message de la même conversation remplace le premier.
                payload['body'] = 'Nadia : Et la page 13.'
                cdp.send('ServiceWorker.deliverPushMessage', {
                    'origin': self.live_server_url, 'registrationId': registration_id, 'data': json.dumps(payload)})
                shown = wait_notifications(page, lambda items: items and items[0][1] == 'Nadia : Et la page 13.')
                self.assertEqual(len(shown), 1, 'une seule notification par conversation')
                self.assertEqual(shown[0][1], 'Nadia : Et la page 13.')
            finally:
                context.close()
