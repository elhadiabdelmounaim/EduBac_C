"""
ASGI config for EduBac — HTTP + WebSocket (Channels).
"""
import os
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.sessions import SessionMiddlewareStack
from chat.middleware import EduBacAuthMiddlewareStack
from chat.routing import websocket_urlpatterns as chat_ws
from whiteboard.routing import websocket_urlpatterns as whiteboard_ws

application = ProtocolTypeRouter({
    'http': django_asgi_app,
    'websocket': SessionMiddlewareStack(
        EduBacAuthMiddlewareStack(
            URLRouter(chat_ws + whiteboard_ws)
        )
    ),
})
