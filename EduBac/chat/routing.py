from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'ws/chat/(?P<classroom_id>\d+)/$', consumers.ChatConsumer.as_asgi()),
    re_path(
        r'ws/chat/(?P<kind>consultation|direct)/(?P<conversation_id>\d+)/$',
        consumers.ConversationConsumer.as_asgi(),
    ),
]
