"""Reconnaissance de l'écriture manuscrite (texte et formules) — sans IA générative.

Le navigateur envoie les tracés bruts sélectionnés (x, y, t de chaque trait) ;
le serveur les transmet à un moteur spécialisé de reconnaissance de
l'écriture : MyScript (iink, API REST « batch »). Les clés restent sur le
serveur ; le navigateur ne les voit jamais.

Activation (.env) :
    MATHBOARD_RECOGNITION=myscript
    MYSCRIPT_APPLICATION_KEY=<clé d'application>
    MYSCRIPT_HMAC_KEY=<clé HMAC>
    (facultatif) MYSCRIPT_HOST=cloud.myscript.com

Offre gratuite MyScript : 2 000 requêtes, pour les essais et le développement ;
la mise en production se fait sur contrat (developer.myscript.com/pricing).
Une conversion = une requête. Sans configuration, la fonction est masquée ;
les formes, le lasso et la gomme fonctionnent sans elle.
"""
import hashlib
import hmac
import json
import logging
import math

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

KINDS = {'text': 'Text', 'math': 'Math'}
LANGS = {'fr_FR', 'ar'}
MAX_STROKES = 400
MAX_POINTS = 3000           # par trait
MAX_TOTAL_POINTS = 40000
TIMEOUT = 20


class RecognitionError(Exception):
    """Message destiné à l'utilisateur (français)."""


def enabled():
    return (settings.MATHBOARD_RECOGNITION == 'myscript'
            and bool(settings.MYSCRIPT_APPLICATION_KEY and settings.MYSCRIPT_HMAC_KEY))


def _numbers(values, what):
    if not isinstance(values, list) or not values:
        raise RecognitionError(f'Tracé invalide ({what}).')
    out = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise RecognitionError(f'Tracé invalide ({what}).')
        out.append(round(float(value), 1))
    return out


def clean_request(data):
    """Valide la demande du navigateur ; renvoie (kind, lang, strokes, width, height)."""
    if not isinstance(data, dict):
        raise RecognitionError('Demande invalide.')
    kind = data.get('kind')
    if kind not in KINDS:
        raise RecognitionError('Type de conversion inconnu.')
    lang = data.get('lang') if data.get('lang') in LANGS else 'fr_FR'
    raw = data.get('strokes')
    if not isinstance(raw, list) or not raw:
        raise RecognitionError('Sélectionnez des traits écrits à la main.')
    if len(raw) > MAX_STROKES:
        raise RecognitionError('Sélection trop grande : convertissez-la en plusieurs fois.')
    strokes, total = [], 0
    for stroke in raw:
        if not isinstance(stroke, dict):
            raise RecognitionError('Tracé invalide.')
        x, y = _numbers(stroke.get('x'), 'x'), _numbers(stroke.get('y'), 'y')
        t = stroke.get('t')
        t = [int(v) for v in _numbers(t, 't')] if t is not None else None
        if len(x) != len(y) or (t is not None and len(t) != len(x)) or len(x) > MAX_POINTS:
            raise RecognitionError('Tracé invalide.')
        total += len(x)
        if total > MAX_TOTAL_POINTS:
            raise RecognitionError('Sélection trop grande : convertissez-la en plusieurs fois.')
        item = {'x': x, 'y': y, 'pointerType': 'PEN'}
        if t is not None:
            item['t'] = t
        strokes.append(item)
    size = []
    for key in ('width', 'height'):
        value = data.get(key)
        size.append(int(min(max(value, 1), 100000)) if isinstance(value, (int, float)) and math.isfinite(value) else None)
    return kind, lang, strokes, size[0], size[1]


def batch_body(kind, lang, strokes, width=None, height=None):
    body = {
        'xDPI': 96, 'yDPI': 96,
        'contentType': KINDS[kind],
        'configuration': {'lang': lang},
        'strokeGroups': [{'strokes': strokes}],
    }
    if width and height:
        body.update(width=width, height=height)
    return body


def signature(payload):
    """HMAC-SHA512 du corps exact envoyé, clé = clé d'application + clé HMAC (hexadécimal)."""
    key = (settings.MYSCRIPT_APPLICATION_KEY + settings.MYSCRIPT_HMAC_KEY).encode()
    return hmac.new(key, payload, hashlib.sha512).hexdigest()


def recognize(kind, lang, strokes, width=None, height=None):
    """Renvoie le texte (kind='text') ou le LaTeX (kind='math') reconnu."""
    payload = json.dumps(batch_body(kind, lang, strokes, width, height), separators=(',', ':')).encode()
    accept = 'application/x-latex' if kind == 'math' else 'text/plain'
    try:
        response = requests.post(
            f'https://{settings.MYSCRIPT_HOST}/api/v4.0/iink/batch', data=payload, timeout=TIMEOUT,
            headers={'applicationKey': settings.MYSCRIPT_APPLICATION_KEY, 'hmac': signature(payload),
                     'Content-Type': 'application/json', 'Accept': accept})
    except requests.Timeout:
        raise RecognitionError('Le service de reconnaissance ne répond pas. Réessayez.')
    except requests.RequestException:
        raise RecognitionError('Service de reconnaissance injoignable depuis le serveur.')
    if response.status_code in (401, 403):
        logger.error('MyScript : accès refusé (%s) %s', response.status_code, response.text[:300])
        raise RecognitionError('Clés MyScript refusées : vérifiez la configuration du serveur.')
    if response.status_code == 429 or 'quota' in response.text[:300].lower():
        raise RecognitionError('Quota de reconnaissance atteint pour le moment.')
    if response.status_code != 200:
        logger.error('MyScript : erreur %s %s', response.status_code, response.text[:300])
        raise RecognitionError('Le service de reconnaissance a rencontré une erreur. Réessayez.')
    result = _result(response, accept).strip()
    if not result:
        raise RecognitionError('Écriture non reconnue : écrivez plus nettement ou sélectionnez moins de traits.')
    return result[:5000]


def _result(response, accept):
    # Réponse attendue : le contenu exporté au type demandé (texte ou LaTeX).
    # Par prudence, une réponse JSON (export JIIX ou « exports ») est aussi lue.
    if 'json' not in response.headers.get('Content-Type', ''):
        return response.text
    try:
        data = response.json()
    except ValueError:
        return response.text
    if isinstance(data, dict):
        exports = data.get('exports') if isinstance(data.get('exports'), dict) else data
        for key in (accept, 'label', 'text'):
            if isinstance(exports.get(key), str):
                return exports[key]
    return ''
