"""Diffusion temps réel (Channels) pour les trois messageries.

Les vues restent la seule porte d'écriture (CSRF + permissions). Le WebSocket
ne fait que prévenir les navigateurs ouverts qu'il faut se mettre à jour ;
l'absence de WebSocket n'empêche jamais l'envoi (repli sur l'interrogation).
"""
import logging

logger = logging.getLogger(__name__)

KIND_CONSULTATION = 'consultation'
KIND_DIRECT = 'direct'


def class_group(classroom_id):
    return f'chat_{classroom_id}'


def conversation_group(kind, conversation_id):
    return f'chat_{kind}_{conversation_id}'


def _send(group, event):
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer
        layer = get_channel_layer()
        if layer:
            async_to_sync(layer.group_send)(group, event)
    except Exception:
        logger.warning('chat broadcast failed group=%s', group, exc_info=True)


def class_message(classroom_id, message):
    """Nouveau message du salon (payload complet, sans droits propres au lecteur)."""
    _send(class_group(classroom_id), {'type': 'chat.message', 'message': message.to_dict()})


def class_update(classroom_id, message):
    """Message modifié, supprimé ou épinglé."""
    _send(class_group(classroom_id), {'type': 'chat.update', 'message': message.to_dict()})


def class_room_changed(classroom_id):
    """Réglages du salon modifiés (verrouillage, heures de silence…)."""
    _send(class_group(classroom_id), {'type': 'chat.room'})


def conversation_changed(kind, conversation_id, event='message'):
    _send(conversation_group(kind, conversation_id), {'type': 'conversation.event', 'event': event})
