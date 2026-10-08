"""WebSocket Whiteboard — sync temps réel des actions de dessin."""
import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async


class WhiteboardConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.board_id = self.scope['url_route']['kwargs']['board_id']
        self.group_name = f'whiteboard_{self.board_id}'
        user = self.scope.get('user')
        if not user or not getattr(user, 'is_authenticated', False):
            await self.close()
            return
        allowed = await self._can_access(user, self.board_id)
        if not allowed:
            await self.close()
            return
        self.can_edit = await self._can_edit(user, self.board_id)
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await self.send(text_data=json.dumps({
            'type': 'ready',
            'can_edit': self.can_edit,
            'board_id': int(self.board_id),
        }))

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        if not text_data:
            return
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            return
        msg_type = data.get('type')
        if msg_type in ('stroke', 'object', 'clear', 'undo_remote', 'content_sync'):
            # Recheck permissions: a teacher may revoke editing during a session.
            self.can_edit = await self._can_edit(self.scope.get('user'), self.board_id)
            if not self.can_edit:
                return
            data['sender'] = self.channel_name
            await self.channel_layer.group_send(
                self.group_name,
                {'type': 'board.event', 'payload': data},
            )
            if msg_type == 'content_sync' and self.can_edit:
                await self._save_content(data.get('content'))

    async def board_event(self, event):
        payload = event['payload']
        # Ne pas renvoyer à l'émetteur
        if payload.get('sender') == self.channel_name:
            return
        await self.send(text_data=json.dumps(payload))

    @database_sync_to_async
    def _can_access(self, user, board_id):
        from .models import WhiteboardBoard
        from .permissions import user_can_access_board
        try:
            board = WhiteboardBoard.objects.select_related('classroom').get(
                pk=board_id, is_active=True
            )
        except WhiteboardBoard.DoesNotExist:
            return False
        return user_can_access_board(user, board)

    @database_sync_to_async
    def _can_edit(self, user, board_id):
        from .models import WhiteboardBoard
        from .permissions import user_can_edit_board
        try:
            board = WhiteboardBoard.objects.select_related('classroom').get(
                pk=board_id, is_active=True
            )
        except WhiteboardBoard.DoesNotExist:
            return False
        return user_can_edit_board(user, board)

    @database_sync_to_async
    def _save_content(self, content):
        if not content:
            return
        from .models import WhiteboardBoard
        WhiteboardBoard.objects.filter(pk=self.board_id).update(content=content)


class WhiteboardShareConsumer(AsyncWebsocketConsumer):
    """Annonce un nouveau partage. Les clients ne peuvent pas publier."""

    async def connect(self):
        self.classroom_id = self.scope['url_route']['kwargs']['classroom_id']
        user = self.scope.get('user')
        if not user or not getattr(user, 'is_authenticated', False):
            await self.close()
            return
        if not await self._can_access(user, self.classroom_id):
            await self.close()
            return
        self.group_name = f'whiteboard_share_{self.classroom_id}'
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        return

    async def share_event(self, event):
        await self.send(text_data=json.dumps(event.get('payload') or {}))

    @database_sync_to_async
    def _can_access(self, user, classroom_id):
        from classrooms.models import Classroom
        from .permissions import user_can_access_classroom
        try:
            classroom = Classroom.objects.get(pk=classroom_id)
        except Classroom.DoesNotExist:
            return False
        return user_can_access_classroom(user, classroom)
