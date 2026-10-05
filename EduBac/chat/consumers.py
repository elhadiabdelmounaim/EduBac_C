import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async


class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.classroom_id = self.scope['url_route']['kwargs']['classroom_id']
        self.group_name = f'chat_{self.classroom_id}'
        user = self.scope.get('user')
        allowed = await self._can_access(user, self.classroom_id)
        if not allowed:
            await self.close()
            return
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        # Les envois passent par l'API HTTP (CSRF + permissions).
        # Le WebSocket sert surtout à la diffusion.
        pass

    async def chat_message(self, event):
        await self.send(text_data=json.dumps({
            'type': 'message',
            'message': event['message'],
        }))

    @database_sync_to_async
    def _can_access(self, user, classroom_id):
        from classrooms.models import Classroom
        from chat.permissions import user_can_access_classroom
        if not user or not getattr(user, 'is_authenticated', False):
            # Essayer session user_id
            session = self.scope.get('session') or {}
            uid = session.get('user_id')
            if not uid:
                return False
            from accounts.models import User
            try:
                user = User.objects.get(pk=uid)
            except User.DoesNotExist:
                return False
        try:
            classroom = Classroom.objects.get(pk=classroom_id)
        except Classroom.DoesNotExist:
            return False
        return user_can_access_classroom(user, classroom)
