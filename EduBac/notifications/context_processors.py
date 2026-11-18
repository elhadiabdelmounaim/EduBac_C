from .push import is_configured, public_key


def web_push(request):
    """Clé publique VAPID pour le bouton « Activer les notifications sur ce téléphone »."""
    return {'webpush_public_key': public_key() if is_configured() else ''}
