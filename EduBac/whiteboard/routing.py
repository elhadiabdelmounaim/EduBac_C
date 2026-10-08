from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(
        r'ws/whiteboard/classe/(?P<classroom_id>\d+)/$',
        consumers.WhiteboardShareConsumer.as_asgi(),
    ),
    re_path(r'ws/whiteboard/(?P<board_id>\d+)/$', consumers.WhiteboardConsumer.as_asgi()),
]
