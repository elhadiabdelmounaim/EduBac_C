from django.urls import path
from . import views

app_name = 'chat'

urlpatterns = [
    path('', views.chat_home, name='home'),
    path('consultations/', views.private_inbox, name='private_inbox'),
    path(
        'consultations/classe/<int:classroom_id>/',
        views.private_student_chat,
        name='private_student_chat',
    ),
    path(
        'consultations/<int:conversation_id>/',
        views.private_room,
        name='private_room',
    ),
    path('classe/<int:classroom_id>/', views.chat_room, name='room'),
    path('api/rooms/', views.api_rooms, name='api_rooms'),
    path(
        'api/consultations/<int:conversation_id>/messages/',
        views.api_private_messages,
        name='api_private_messages',
    ),
    path(
        'api/consultations/<int:conversation_id>/send/',
        views.api_private_send,
        name='api_private_send',
    ),
    path(
        'consultations/attachments/<int:message_id>/',
        views.private_attachment,
        name='private_attachment',
    ),
    path('api/classe/<int:classroom_id>/messages/', views.api_messages, name='api_messages'),
    path('attachments/<int:message_id>/', views.attachment, name='attachment'),
    path('api/classe/<int:classroom_id>/send/', views.api_send, name='api_send'),
    path('api/classe/<int:classroom_id>/read/', views.api_mark_read, name='api_read'),
    path('api/unread/', views.api_unread_total, name='api_unread'),
    path('api/classe/<int:classroom_id>/pin/<int:message_id>/', views.api_pin, name='api_pin'),
]
