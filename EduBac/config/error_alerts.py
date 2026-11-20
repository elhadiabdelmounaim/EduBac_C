"""Alertes d'erreurs pour l'administration, sans e-mail.

- Erreurs du serveur (réponse 500, journal « django.request ») ;
- erreurs JavaScript survenues dans le navigateur d'un utilisateur
  (journal « edubac.client », rapportées par static/js/error-report.js).

Chaque erreur devient une notification dans EduBac (et sur le téléphone si les
notifications push sont activées) pour les administrateurs. Une même erreur
n'est signalée qu'une fois par heure ; le nombre d'occurrences est mis à jour.
"""
import hashlib
import logging
import threading

REPEAT_SECONDS = 3600
_local = threading.local()


def _fingerprint(record):
    message = record.getMessage().splitlines()[0][:200] if record.getMessage() else ''
    where = getattr(record, 'error_where', '') or f'{record.pathname}:{record.lineno}'
    exc = record.exc_info[0].__name__ if record.exc_info and record.exc_info[0] else ''
    return hashlib.sha1(f'{record.name}|{exc}|{where}|{message}'.encode()).hexdigest()[:16]


def _summary(record):
    if record.name == 'edubac.client':
        return 'Erreur dans le navigateur', record.getMessage()[:400]
    request = getattr(record, 'request', None)
    path = getattr(request, 'path', '') if request is not None else ''
    exc = record.exc_info[1] if record.exc_info else None
    detail = f'{type(exc).__name__} : {exc}' if exc else record.getMessage()
    return 'Erreur du serveur', f'{path} — {detail}'[:400]


class AdminAlertHandler(logging.Handler):
    def emit(self, record):
        if getattr(_local, 'busy', False):  # une erreur pendant l'alerte : pas de boucle
            return
        _local.busy = True
        try:
            from django.contrib.auth import get_user_model
            from django.core.cache import cache
            from django.db.models import Q
            from notifications.models import Notification

            key = f'error-alert:{_fingerprint(record)}'
            try:
                count = cache.incr(key)
            except ValueError:
                cache.set(key, 1, REPEAT_SECONDS)
                count = 1
            if count not in (1, 10, 100, 1000):
                return
            title, message = _summary(record)
            if count > 1:
                message = f'{message} ({count} fois depuis une heure)'
            admins = get_user_model().objects.filter(Q(is_superuser=True) | Q(is_staff=True), is_active=True)
            for admin in admins:
                Notification.notify(admin, title=title, message=message, type='system', send_email=False,
                                    group_key=key)
        except Exception:  # l'alerte ne doit jamais aggraver la panne
            pass
        finally:
            _local.busy = False
