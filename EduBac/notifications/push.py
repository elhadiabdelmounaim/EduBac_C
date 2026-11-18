"""Notifications sur le téléphone (Web Push), sans dépendance supplémentaire.

- Chiffrement du message : RFC 8291 (« aes128gcm »), avec `cryptography`.
- Identification du serveur : VAPID, RFC 8292 (jeton JWT ES256).
- Envoi : urllib, vers le service de push du navigateur (Google, Apple, Mozilla…).

Les envois sont faits **après** la réponse HTTP (signal `request_finished`) :
la personne qui écrit un message n'attend jamais les services de push.
Hors requête (commande, tâche planifiée), ils partent immédiatement.

Clés : `python manage.py generate_vapid_keys`, puis WEBPUSH_VAPID_PUBLIC_KEY,
WEBPUSH_VAPID_PRIVATE_KEY et WEBPUSH_CONTACT dans `.env`. Sans clés, rien n'est
envoyé et le bouton d'activation n'apparaît pas.
"""
import base64
import json
import logging
import os
import struct
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from django.conf import settings
from django.core.signals import request_finished, request_started
from django.utils import timezone

logger = logging.getLogger(__name__)

TTL_SECONDS = 24 * 3600
TIMEOUT_SECONDS = 5
MAX_PAYLOAD_BYTES = 3000
# Seuls les services de push des navigateurs sont contactés (pas de requête vers une adresse arbitraire).
ALLOWED_PUSH_HOSTS = (
    'fcm.googleapis.com', 'android.googleapis.com', 'updates.push.services.mozilla.com',
    'push.services.mozilla.com', 'web.push.apple.com', '.push.apple.com', '.notify.windows.com',
)


def b64url_encode(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def b64url_decode(text):
    text = str(text or '').strip()
    return base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))


def public_key():
    return getattr(settings, 'WEBPUSH_VAPID_PUBLIC_KEY', '') or ''


def is_configured():
    return bool(public_key() and getattr(settings, 'WEBPUSH_VAPID_PRIVATE_KEY', ''))


def endpoint_allowed(endpoint):
    try:
        parts = urlsplit(endpoint)
    except ValueError:
        return False
    host = (parts.hostname or '').lower()
    if parts.scheme != 'https' or not host:
        return False
    return any(host == allowed or (allowed.startswith('.') and host.endswith(allowed))
               for allowed in ALLOWED_PUSH_HOSTS)


# --- Cryptographie --------------------------------------------------------------

def generate_vapid_keys():
    """(clé publique, clé privée) en base64url, à placer dans .env."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    private = ec.generate_private_key(ec.SECP256R1())
    raw_private = private.private_numbers().private_value.to_bytes(32, 'big')
    raw_public = private.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint,
    )
    return b64url_encode(raw_public), b64url_encode(raw_private)


def _vapid_private_key():
    from cryptography.hazmat.primitives.asymmetric import ec

    value = int.from_bytes(b64url_decode(settings.WEBPUSH_VAPID_PRIVATE_KEY), 'big')
    return ec.derive_private_key(value, ec.SECP256R1())


def vapid_authorization(endpoint, now=None):
    """En-tête Authorization « vapid t=…, k=… » pour le service de push de l'abonnement."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

    parts = urlsplit(endpoint)
    claims = {
        'aud': f'{parts.scheme}://{parts.netloc}',
        'exp': int((now or time.time()) + 12 * 3600),
        'sub': getattr(settings, 'WEBPUSH_CONTACT', '') or 'mailto:admin@edubac.invalid',
    }
    header = b64url_encode(json.dumps({'typ': 'JWT', 'alg': 'ES256'}, separators=(',', ':')).encode())
    body = b64url_encode(json.dumps(claims, separators=(',', ':')).encode())
    signing_input = f'{header}.{body}'.encode('ascii')
    der = _vapid_private_key().sign(signing_input, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    signature = b64url_encode(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))
    return f'vapid t={header}.{body}.{signature}, k={public_key()}'


def encrypt(payload, p256dh, auth, salt=None, server_private=None):
    """Chiffre `payload` (bytes) pour l'appareil, au format aes128gcm (RFC 8291)."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    def hkdf(salt_value, ikm, info, length):
        return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt_value, info=info).derive(ikm)

    ua_public_raw = b64url_decode(p256dh)
    auth_secret = b64url_decode(auth)
    ua_public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public_raw)
    server_private = server_private or ec.generate_private_key(ec.SECP256R1())
    as_public_raw = server_private.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint,
    )
    shared = server_private.exchange(ec.ECDH(), ua_public)
    ikm = hkdf(auth_secret, shared, b'WebPush: info\x00' + ua_public_raw + as_public_raw, 32)
    salt = salt or os.urandom(16)
    cek = hkdf(salt, ikm, b'Content-Encoding: aes128gcm\x00', 16)
    nonce = hkdf(salt, ikm, b'Content-Encoding: nonce\x00', 12)
    ciphertext = AESGCM(cek).encrypt(nonce, payload + b'\x02', None)
    header = salt + struct.pack('!L', 4096) + bytes([len(as_public_raw)]) + as_public_raw
    return header + ciphertext


# --- Envoi -----------------------------------------------------------------------

def _post(subscription, body, urgency='high', topic=''):
    headers = {
        'Authorization': vapid_authorization(subscription.endpoint),
        'Content-Encoding': 'aes128gcm',
        'Content-Type': 'application/octet-stream',
        'TTL': str(TTL_SECONDS),
        'Urgency': urgency,
    }
    if topic:
        headers['Topic'] = topic[:32]
    request = urllib.request.Request(subscription.endpoint, data=body, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


def send_to_subscription(subscription, payload):
    """Envoie un message à un appareil. Les abonnements expirés sont supprimés."""
    data = json.dumps(payload, ensure_ascii=False).encode('utf-8')[:MAX_PAYLOAD_BYTES]
    try:
        body = encrypt(data, subscription.p256dh, subscription.auth)
        topic = ''.join(c for c in str(payload.get('tag', '')) if c.isalnum())[:32]
        status = _post(subscription, body, topic=topic)
    except Exception:
        logger.warning('web push failed endpoint=%s', subscription.endpoint[:60], exc_info=True)
        status = None
    if status in (404, 410):
        subscription.delete()  # désinstallé ou notifications révoquées sur l'appareil
        return False
    if status and 200 <= status < 300:
        type(subscription).objects.filter(pk=subscription.pk).update(last_success_at=timezone.now(), failures=0)
        return True
    from django.db.models import F
    type(subscription).objects.filter(pk=subscription.pk).update(failures=F('failures') + 1)
    return False


def deliver(user_ids, payload):
    """Envoie immédiatement à tous les appareils des utilisateurs."""
    from .models import PushSubscription

    if not is_configured() or not user_ids:
        return 0
    sent = 0
    for subscription in PushSubscription.objects.filter(user_id__in=set(user_ids), failures__lt=20):
        sent += bool(send_to_subscription(subscription, payload))
    return sent


# --- File d'attente « après la réponse » --------------------------------------------

_state = threading.local()


def _queue():
    if not hasattr(_state, 'items'):
        _state.items = []
        _state.in_request = False
    return _state


def push_to_users(user_ids, title, body, url='/', tag=''):
    """Programme une notification sur les appareils des utilisateurs."""
    if not is_configured():
        return
    user_ids = [uid for uid in set(user_ids) if uid]
    if not user_ids:
        return
    payload = {
        'title': str(title)[:120],
        'body': str(body)[:300],
        'url': url if str(url).startswith('/') else '/',
        'tag': str(tag)[:60] or f'edubac-{int(time.time() * 1000)}',
        'icon': '/static/pwa/icon-192.png',
        'badge': '/static/pwa/icon-maskable-192.png',
    }
    state = _queue()
    if state.in_request and not getattr(settings, 'WEBPUSH_SEND_IMMEDIATELY', False):
        state.items.append((user_ids, payload))
    else:
        deliver(user_ids, payload)


def _request_started(**kwargs):
    state = _queue()
    state.items = []
    state.in_request = True


def _request_finished(**kwargs):
    state = _queue()
    items, state.items, state.in_request = state.items, [], False
    for user_ids, payload in items:
        try:
            deliver(user_ids, payload)
        except Exception:
            logger.warning('web push flush failed', exc_info=True)


request_started.connect(_request_started, dispatch_uid='edubac_push_started')
request_finished.connect(_request_finished, dispatch_uid='edubac_push_finished')
