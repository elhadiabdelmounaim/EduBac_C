"""{% asset 'css/x.css' %} → /static/css/x.css?v=<empreinte du contenu>.

Plus de numéros de version à changer à la main : dès qu'un fichier CSS/JS est
modifié, son adresse change et les navigateurs (et le service worker) chargent
la nouvelle version. L'empreinte est recalculée si le fichier change sur le disque.
"""
import hashlib
import os

from django import template
from django.conf import settings
from django.contrib.staticfiles import finders

register = template.Library()
_cache = {}


def _locate(path):
    found = finders.find(path)
    if found:
        return found
    root = getattr(settings, 'STATIC_ROOT', None)
    if root:
        candidate = os.path.join(root, path)
        if os.path.exists(candidate):
            return candidate
    return None


def asset_url(path):
    path = str(path).lstrip('/')
    base = settings.STATIC_URL.rstrip('/') + '/' + path
    filename = _locate(path)
    if not filename:
        return base
    try:
        mtime = os.stat(filename).st_mtime_ns
    except OSError:
        return base
    cached = _cache.get(filename)
    if not cached or cached[0] != mtime:
        with open(filename, 'rb') as handle:
            digest = hashlib.sha256(handle.read()).hexdigest()[:10]
        cached = (mtime, digest)
        _cache[filename] = cached
    return f'{base}?v={cached[1]}'


@register.simple_tag
def asset(path):
    return asset_url(path)
