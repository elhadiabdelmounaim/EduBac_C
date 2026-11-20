"""Réception des erreurs JavaScript des navigateurs (static/js/error-report.js).

Aucune donnée saisie par l'utilisateur n'est transmise : message d'erreur,
fichier, ligne, page, navigateur. Limité en taille et en fréquence par adresse.
"""
import json
import logging
from urllib.parse import urlparse

from django.core.cache import cache
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

logger = logging.getLogger('edubac.client')
MAX_BODY = 8000
PER_MINUTE = 20
IGNORED = ('ResizeObserver loop', 'Script error.', 'Load failed', 'NetworkError', 'Failed to fetch',
           'AbortError', 'The user aborted a request')


def _same_site(request, url):
    host = urlparse(url or '').netloc
    return not host or host == request.get_host()


@csrf_exempt  # envoyé par navigator.sendBeacon, sans jeton ; rien n'est modifié
@require_POST
def client_error(request):
    ip = request.META.get('HTTP_X_REAL_IP') or request.META.get('REMOTE_ADDR', '')
    key = f'client-errors:{ip}'
    try:
        count = cache.incr(key)
    except ValueError:
        cache.set(key, 1, 60)
        count = 1
    if count > PER_MINUTE or len(request.body) > MAX_BODY:
        return HttpResponse(status=204)
    if not _same_site(request, request.META.get('HTTP_ORIGIN')) or not _same_site(request, request.META.get('HTTP_REFERER')):
        return HttpResponse(status=204)
    try:
        data = json.loads(request.body.decode('utf-8'))
    except (UnicodeDecodeError, ValueError):
        return HttpResponse(status=204)
    if not isinstance(data, dict):
        return HttpResponse(status=204)
    message = ' '.join(str(data.get('message') or '').split())[:300]
    if not message or any(text in message for text in IGNORED):
        return HttpResponse(status=204)
    source = str(data.get('source') or '')[:200]
    if source and not _same_site(request, source):
        return HttpResponse(status=204)  # extension ou script d'un autre site
    page = urlparse(str(data.get('page') or '')).path[:200]
    where = f'{urlparse(source).path}:{data.get("line") or "?"}' if source else page
    user = getattr(request, 'edubac_user', None)
    who = (user.get_full_name() or user.username) if user else 'visiteur'
    role = 'élève' if user and user.is_student() else ('professeur' if user and user.is_teacher() else '')
    agent = request.META.get('HTTP_USER_AGENT', '')[:120]
    logger.error('%s — page %s, %s — %s%s — %s', message, page or '?', where, who, f' ({role})' if role else '', agent,
                 extra={'error_where': where})
    return HttpResponse(status=204)
