from pathlib import Path

from django.conf import settings
from django.test import TestCase, override_settings
from PIL import Image

from accounts.models import User

STATIC = Path(settings.BASE_DIR) / 'static'


@override_settings(ALLOWED_HOSTS=['testserver'])
class ProgressiveWebAppTests(TestCase):
    def test_manifest_has_installable_fields_and_existing_icons(self):
        response = self.client.get('/manifest.webmanifest')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response['Content-Type'].startswith('application/manifest+json'))
        data = response.json()
        self.assertEqual(data['name'], 'EduBac')
        self.assertEqual(data['short_name'], 'EduBac')
        self.assertEqual(data['display'], 'standalone')
        self.assertEqual(data['start_url'], '/')
        self.assertEqual(data['scope'], '/')
        self.assertEqual(data['theme_color'], '#12306b')
        self.assertEqual(data['background_color'], '#f4f6fb')
        purposes = {(icon['sizes'], icon['purpose']) for icon in data['icons']}
        for size in ('192x192', '512x512'):
            self.assertIn((size, 'any'), purposes)
            self.assertIn((size, 'maskable'), purposes)
        for icon in data['icons']:
            path = STATIC / icon['src'].removeprefix('/static/')
            with Image.open(path) as image:
                self.assertEqual(f'{image.width}x{image.height}', icon['sizes'], icon['src'])

    def test_apple_icon_is_opaque_180_pixels(self):
        with Image.open(STATIC / 'pwa' / 'apple-touch-icon.png') as image:
            self.assertEqual(image.size, (180, 180))
            self.assertEqual(image.mode, 'RGB', 'iOS affiche en noir les zones transparentes')

    def test_service_worker_is_served_at_the_root_and_always_revalidated(self):
        response = self.client.get('/service-worker.js')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response['Content-Type'].startswith('application/javascript'))
        self.assertIn('no-cache', response['Cache-Control'])
        self.assertEqual(response['Service-Worker-Allowed'], '/')
        script = response.content.decode()
        self.assertIn("'/hors-ligne/'", script)
        self.assertNotIn('{{', script)

    def test_service_worker_only_caches_public_static_files(self):
        script = self.client.get('/service-worker.js').content.decode()
        self.assertIn("if (request.method !== 'GET') return;", script)
        self.assertIn("url.pathname.startsWith('/static/')", script)
        self.assertIn('if (url.origin !== self.location.origin) return;', script)
        # Les navigations passent par le réseau ; seul le repli hors ligne vient du cache.
        navigate = script.split('async function navigate', 1)[1].split('async function staticAsset', 1)[0]
        self.assertNotIn('cache.put', navigate)
        self.assertEqual(script.count('cache.put('), 1)

    def test_offline_page_is_public_and_contains_no_personal_data(self):
        student = User.objects.create_user(username='eleve-pwa', email='pwa@example.test',
                                           first_name='Yasmine', role='student')
        session = self.client.session
        session['user_id'] = student.pk
        session.save()
        response = self.client.get('/hors-ligne/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Vous êtes hors connexion')
        self.assertNotContains(response, 'Yasmine')
        self.assertNotContains(response, 'csrfmiddlewaretoken')
        self.assertNotContains(response, 'eleve-pwa')

    def test_every_page_links_the_manifest_ios_tags_and_install_entry(self):
        page = self.client.get('/compte/connexion/')
        for marker in ('rel="manifest" href="/manifest.webmanifest"', 'name="theme-color" content="#12306b"',
                       'rel="apple-touch-icon"', 'apple-mobile-web-app-capable', 'apple-touch-startup-image',
                       'data-pwa-install', 'id="pwaBanner"', '/static/js/pwa.js'):
            self.assertContains(page, marker)

    def test_splash_screens_referenced_in_templates_exist(self):
        head = (Path(settings.BASE_DIR) / 'templates' / 'includes' / 'pwa_head.html').read_text()
        import re
        for path in re.findall(r'href="/static/(pwa/[^"]+)"', head):
            self.assertTrue((STATIC / path).exists(), path)
