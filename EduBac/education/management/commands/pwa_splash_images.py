"""Génère les écrans de lancement iPhone/iPad (static/pwa/splash-*.png) à partir
de l'écran de chargement EduBac (/bienvenue/), pour que l'image affichée par iOS
au lancement soit identique à la page qui la remplace.

À lancer sur l'ordinateur de développement (Playwright est une dépendance de
développement, voir requirements-dev.txt), puis committer les images :

    python manage.py pwa_splash_images

Aucun serveur n'est nécessaire : la page est rendue par Django et les fichiers
/static/ sont lus sur le disque.
"""
import io
import mimetypes
import os
import shutil
from pathlib import Path
from urllib.parse import urlparse

from django.conf import settings
from django.contrib.staticfiles import finders
from django.core.management.base import BaseCommand, CommandError
from django.test import RequestFactory

# (largeur px, hauteur px, densité, hauteur de la barre d'état en points).
# En mode application, iOS affiche la page sous la barre d'état : l'image garde
# cette bande pour que le logo tombe exactement au même endroit.
DEVICES = (
    (750, 1334, 2, 20),     # iPhone SE, 8
    (828, 1792, 2, 48),     # iPhone XR, 11
    (1125, 2436, 3, 44),    # iPhone X, XS, 11 Pro, mini
    (1170, 2532, 3, 47),    # iPhone 12, 13, 14
    (1179, 2556, 3, 59),    # iPhone 14 Pro, 15, 16
    (1284, 2778, 3, 47),    # iPhone 12-14 Pro Max, 14 Plus
    (1290, 2796, 3, 59),    # iPhone 15 Plus, 15-16 Pro Max
    (1536, 2048, 2, 20),    # iPad (portrait)
)
STATUS_BAR_COLOR = (255, 255, 255)
ORIGIN = 'https://edubac.local'


class Command(BaseCommand):
    help = "Génère les écrans de lancement iOS à partir de l'écran de chargement EduBac."

    def handle(self, *args, **options):
        try:
            from PIL import Image
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise CommandError(f'Dépendance de développement manquante : {exc}') from exc

        from education.views import welcome
        request = RequestFactory().get('/bienvenue/', HTTP_HOST='edubac.local')
        request.session = {}
        request.edubac_user = None
        html = welcome(request).content

        def serve(route):
            url = urlparse(route.request.url)
            if url.path == '/bienvenue/':
                return route.fulfill(body=html, content_type='text/html; charset=utf-8')
            if url.path.startswith(settings.STATIC_URL):
                found = finders.find(url.path[len(settings.STATIC_URL):])
                if found:
                    kind = mimetypes.guess_type(found)[0] or 'application/octet-stream'
                    return route.fulfill(body=Path(found).read_bytes(), content_type=kind)
            return route.fulfill(status=404, body=b'')

        out_dir = Path(settings.BASE_DIR) / 'static' / 'pwa'
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                executable_path=os.environ.get('CHROMIUM_EXECUTABLE') or shutil.which('chromium')
                or shutil.which('google-chrome'),
                headless=True, args=['--no-sandbox'])
            for width, height, scale, status_bar in DEVICES:
                css_width = width // scale
                css_height = height // scale - status_bar
                context = browser.new_context(
                    viewport={'width': css_width, 'height': css_height},
                    device_scale_factor=scale, is_mobile=True, has_touch=True,
                    reduced_motion='reduce')
                # État initial figé : barre au début, « Chargement… », pas de fin d'écran.
                context.add_init_script('window.setTimeout = window.setInterval = function () { return 0; };')
                page = context.new_page()
                page.route('**/*', serve)
                page.goto(ORIGIN + '/bienvenue/', wait_until='load')
                page.wait_for_function("[...document.images].every(i => i.complete && i.naturalWidth > 0)")
                page.evaluate("document.fonts.ready")
                shot = Image.open(io.BytesIO(page.screenshot())).convert('RGB')
                context.close()

                image = Image.new('RGB', (width, height), STATUS_BAR_COLOR)
                image.paste(shot, (0, height - shot.height))
                target = out_dir / f'splash-{width}x{height}.png'
                image.save(target, optimize=True)
                self.stdout.write(f'{target.relative_to(settings.BASE_DIR)} ({target.stat().st_size // 1024} Ko)')
            browser.close()
        self.stdout.write(self.style.SUCCESS('Écrans de lancement iOS générés.'))
