"""Diffusion WebSocket des modifications du tableau (accélérateur facultatif).

Les vues HTTP restent la seule porte d'écriture. Sans WebSocket (WSGI), les
clients récupèrent les mêmes opérations par interrogation de /sync/.
"""
import json
import logging

logger = logging.getLogger(__name__)

MAX_PUSH_BYTES = 256 * 1024


def board_group(board_id):
    return f'whiteboard_{board_id}'


def _send(board_id, payload):
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer
        layer = get_channel_layer()
        if layer:
            async_to_sync(layer.group_send)(board_group(board_id), {'type': 'board.event', 'payload': payload})
    except Exception:
        logger.warning('whiteboard broadcast failed board=%s', board_id, exc_info=True)


def board_ops(board_id, revision, ops):
    """Opérations appliquées ; au-delà d'une certaine taille, simple signal « à jour »."""
    if not ops:
        return
    payload = {'type': 'ops', 'revision': revision, 'ops': ops}
    if len(json.dumps(payload)) > MAX_PUSH_BYTES:
        payload = {'type': 'revision', 'revision': revision}
    _send(board_id, payload)


def board_state(board_id):
    """Réglages, contrôle, main levée… : les clients se resynchronisent."""
    _send(board_id, {'type': 'state'})
