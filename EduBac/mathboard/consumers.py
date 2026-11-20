"""Temps réel du tableau mathématique (Django Channels).

- Les écritures passent par l'API HTTP (une seule porte, validée et enregistrée) ;
  ce canal diffuse les opérations acceptées, la présence et les curseurs.
- Droits vérifiés à la connexion et à chaque changement de réglages du document.
- Couche de canaux : Redis en production (REDIS_URL), mémoire en développement.
"""
import time

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from .realtime import group_name

CURSOR_MIN_INTERVAL = 0.05     # secondes entre deux curseurs diffusés
SESSION_SAVE_INTERVAL = 5.0    # secondes entre deux écritures de présence en base


class MathboardConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.document_id = int(self.scope['url_route']['kwargs']['document_id'])
        self.user = self.scope.get('user')
        self.client_id = None
        if not self.user or not getattr(self.user, 'is_authenticated', False):
            await self.close(code=4401)
            return
        self.level = await self._level()
        if self.level is None:
            await self.close(code=4403)
            return
        self.group = group_name(self.document_id)
        self.last_cursor = 0.0
        self.last_saved = 0.0
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        if getattr(self, 'group', None):
            await self.channel_layer.group_discard(self.group, self.channel_name)
            if self.client_id:
                await self._drop_session()
                await self._broadcast_presence()

    async def receive_json(self, content, **kwargs):
        kind = content.get('type') if isinstance(content, dict) else None
        if kind == 'hello':
            self.client_id = str(content.get('client_id', ''))[:64] or None
            if self.client_id:
                await self._save_session(str(content.get('page', ''))[:64], {})
                await self._broadcast_presence()
        elif kind == 'cursor' and self.client_id:
            now = time.monotonic()
            if now - self.last_cursor < CURSOR_MIN_INTERVAL:
                return
            self.last_cursor = now
            try:
                x, y = float(content['x']), float(content['y'])
            except (KeyError, TypeError, ValueError):
                return
            page = str(content.get('page', ''))[:64]
            await self.channel_layer.group_send(self.group, {
                'type': 'board.cursor', 'sender': self.channel_name,
                'cursor': {'client_id': self.client_id, 'user': self.user.pk, 'page': page, 'x': x, 'y': y},
            })
            if now - self.last_saved > SESSION_SAVE_INTERVAL:
                self.last_saved = now
                await self._save_session(page, {'x': x, 'y': y})
        elif kind == 'page' and self.client_id:
            await self._save_session(str(content.get('page', ''))[:64], {})
            await self._broadcast_presence()
        elif kind == 'ping':
            await self.send_json({'type': 'pong'})

    # --- messages du groupe -------------------------------------------------
    async def board_message(self, event):
        message = event['message']
        if message.get('type') == 'document':
            # Réglages modifiés (classe, droits) : on revérifie l'accès.
            self.level = await self._level()
            if self.level is None:
                await self.send_json({'type': 'revoked'})
                await self.close(code=4403)
                return
            message = {**message, 'access': self.level}
        await self.send_json(message)

    async def board_cursor(self, event):
        if event['sender'] != self.channel_name:
            await self.send_json({'type': 'cursor', **event['cursor']})

    async def board_presence(self, event):
        await self.send_json({'type': 'presence', 'users': event['users']})

    # --- base de données ----------------------------------------------------
    @database_sync_to_async
    def _level(self):
        from .access import access_level
        from .models import WhiteboardDocument
        document = WhiteboardDocument.objects.select_related('classroom', 'source__classroom').filter(pk=self.document_id).first()
        return access_level(self.user, document) if document else None

    @database_sync_to_async
    def _save_session(self, page, cursor):
        from .models import WhiteboardSession
        session, _ = WhiteboardSession.objects.get_or_create(
            document_id=self.document_id, client_id=self.client_id, defaults={'user': self.user})
        if session.user_id != self.user.pk:
            return
        session.page_uid = page or session.page_uid
        if cursor:
            session.cursor = cursor
        session.save()

    @database_sync_to_async
    def _drop_session(self):
        from .models import WhiteboardSession
        WhiteboardSession.objects.filter(document_id=self.document_id, client_id=self.client_id,
                                         user=self.user).delete()

    @database_sync_to_async
    def _presence(self):
        from .api import presence_list
        from .models import WhiteboardDocument
        return presence_list(WhiteboardDocument.objects.get(pk=self.document_id))

    async def _broadcast_presence(self):
        await self.channel_layer.group_send(self.group, {'type': 'board.presence', 'users': await self._presence()})
