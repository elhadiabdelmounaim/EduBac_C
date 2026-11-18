import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from .realtime import KIND_CONSULTATION, KIND_DIRECT, class_group, conversation_group


class ChatConsumer(AsyncWebsocketConsumer):
    """Salon de classe : diffuse les nouveaux messages et les modifications."""

    async def connect(self):
        self.classroom_id = self.scope['url_route']['kwargs']['classroom_id']
        user = self.scope.get('user')
        if not await self._can_access(user, self.classroom_id):
            await self.close()
            return
        self.group_name = class_group(self.classroom_id)
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        # Les envois passent par l'API HTTP (CSRF + permissions).
        return

    async def chat_message(self, event):
        await self.send(text_data=json.dumps({'type': 'message', 'message': event['message']}))

    async def chat_update(self, event):
        await self.send(text_data=json.dumps({'type': 'update', 'message': event['message']}))

    async def chat_room(self, event):
        await self.send(text_data=json.dumps({'type': 'room'}))

    @database_sync_to_async
    def _can_access(self, user, classroom_id):
        from classrooms.models import Classroom
        from chat.permissions import user_can_access_classroom
        if not user or not getattr(user, 'is_authenticated', False):
            return False
        classroom = Classroom.objects.filter(pk=classroom_id).first()
        return bool(classroom and user_can_access_classroom(user, classroom))


class ConversationConsumer(AsyncWebsocketConsumer):
    """Consultation ou conversation individuelle : signale qu'il faut se mettre à jour."""

    async def connect(self):
        kwargs = self.scope['url_route']['kwargs']
        self.kind = kwargs['kind']
        self.conversation_id = int(kwargs['conversation_id'])
        user = self.scope.get('user')
        if not await self._can_access(user):
            await self.close()
            return
        self.group_name = conversation_group(self.kind, self.conversation_id)
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        return

    async def conversation_event(self, event):
        await self.send(text_data=json.dumps({'type': event.get('event', 'message')}))

    @database_sync_to_async
    def _can_access(self, user):
        if not user or not getattr(user, 'is_authenticated', False):
            return False
        if self.kind == KIND_CONSULTATION:
            from chat.views import _private_conversations_for
            return _private_conversations_for(user).filter(pk=self.conversation_id).exists()
        if self.kind == KIND_DIRECT:
            from chat.models import DirectConversation
            from chat.permissions import user_can_access_direct_conversation
            conversation = DirectConversation.objects.select_related(
                'participant_one', 'participant_two',
            ).filter(pk=self.conversation_id).first()
            return bool(conversation and user_can_access_direct_conversation(user, conversation))
        return False
