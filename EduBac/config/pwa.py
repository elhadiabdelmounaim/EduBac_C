"""Application installable (PWA) : manifeste, service worker et page hors connexion.

Le service worker est servi à la racine (/service-worker.js) pour contrôler tout
le site. Il ne met en cache que des ressources publiques : fichiers /static/ et
la page hors connexion. Les pages HTML, l'API, les sessions et les fichiers
privés passent toujours par le réseau.
"""
import hashlib
from pathlib import Path

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.views.decorators.http import require_GET

THEME_COLOR = '#185f60'       # barre EduBac (--nb-teal)
BACKGROUND_COLOR = '#f4f1e8'  # fond des pages (--nb-paper)
ICON_DIR = '/static/pwa/'
PRECACHE = [
    '/hors-ligne/',
    ICON_DIR + 'icon-192.png',
    ICON_DIR + 'icon-512.png',
    ICON_DIR + 'apple-touch-icon.png',
]


def _version():
    """Change dès que le service worker, la page hors ligne ou les icônes changent."""
    digest = hashlib.sha256()
    templates = Path(settings.BASE_DIR) / 'templates' / 'pwa'
    icons = Path(settings.BASE_DIR) / 'static' / 'pwa'
    for path in sorted(list(templates.glob('*')) + list(icons.glob('icon-*.png'))):
        digest.update(path.name.encode())
        digest.update(str(path.stat().st_mtime_ns).encode())
    return digest.hexdigest()[:12]


@require_GET
def manifest(request):
    icons = [
        {'src': f'{ICON_DIR}icon-192.png', 'sizes': '192x192', 'type': 'image/png', 'purpose': 'any'},
        {'src': f'{ICON_DIR}icon-512.png', 'sizes': '512x512', 'type': 'image/png', 'purpose': 'any'},
        {'src': f'{ICON_DIR}icon-maskable-192.png', 'sizes': '192x192', 'type': 'image/png', 'purpose': 'maskable'},
        {'src': f'{ICON_DIR}icon-maskable-512.png', 'sizes': '512x512', 'type': 'image/png', 'purpose': 'maskable'},
    ]
    shortcut_icon = [{'src': f'{ICON_DIR}icon-192.png', 'sizes': '192x192', 'type': 'image/png'}]
    data = {
        'id': '/',
        'name': 'EduBac',
        'short_name': 'EduBac',
        'description': 'Cours, quiz, messagerie et tableau blanc de mathématiques pour le Bac.',
        'lang': 'fr',
        'dir': 'ltr',
        'start_url': '/',
        'scope': '/',
        'display': 'standalone',
        'orientation': 'any',
        'theme_color': THEME_COLOR,
        'background_color': BACKGROUND_COLOR,
        'categories': ['education'],
        'prefer_related_applications': False,
        'icons': icons,
        'shortcuts': [
            {'name': 'Messagerie', 'url': '/chat/', 'icons': shortcut_icon},
            {'name': 'Tableau blanc', 'short_name': 'Tableau', 'url': '/tableau/', 'icons': shortcut_icon},
            {'name': 'Notifications', 'url': '/notifications/', 'icons': shortcut_icon},
        ],
    }
    response = JsonResponse(data, json_dumps_params={'ensure_ascii': False, 'indent': 2})
    response['Content-Type'] = 'application/manifest+json; charset=utf-8'
    response['Cache-Control'] = 'public, max-age=3600'
    return response


@require_GET
def service_worker(request):
    script = render_to_string('pwa/service-worker.js', {
        'version': _version(),
        'precache': PRECACHE,
        'offline_url': '/hors-ligne/',
    })
    response = HttpResponse(script, content_type='application/javascript; charset=utf-8')
    # Toujours revalidé : une nouvelle version est prise en compte au prochain chargement.
    response['Cache-Control'] = 'no-cache, max-age=0'
    response['Service-Worker-Allowed'] = '/'
    return response


@require_GET
def offline(request):
    """Page publique, sans donnée personnelle : la seule page HTML mise en cache."""
    response = render(request, 'pwa/offline.html', {
        'theme_color': THEME_COLOR,
        'background_color': BACKGROUND_COLOR,
    })
    response['Cache-Control'] = 'public, max-age=86400'
    return response
