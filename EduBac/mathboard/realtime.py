"""Diffusion temps réel (Channels). Facultative : sans couche de canaux ou sans
WebSocket, les clients récupèrent les mêmes opérations par l'API (?since=)."""
import logging

logger = logging.getLogger(__name__)


def group_name(document_id):
    return f'mathboard_{document_id}'


def publish(document_id, message):
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer
        layer = get_channel_layer()
        if layer is not None:
            async_to_sync(layer.group_send)(group_name(document_id), {'type': 'board.message', 'message': message})
    except Exception:  # la diffusion ne doit jamais faire échouer l'enregistrement
        logger.warning('mathboard publish failed document=%s', document_id, exc_info=True)
