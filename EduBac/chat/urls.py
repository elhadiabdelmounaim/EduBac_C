from django.urls import path
from . import views
from . import direct_views

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
    path(
        'direct/<int:conversation_id>/',
        views.direct_room,
        name='direct_room',
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
    path('api/direct/contacts/', direct_views.api_direct_contacts, name='api_direct_contacts'),
    path('api/direct/start/', direct_views.api_direct_start, name='api_direct_start'),
    path('api/direct/<int:conversation_id>/messages/', direct_views.api_direct_messages, name='api_direct_messages'),
    path('api/direct/<int:conversation_id>/send/', direct_views.api_direct_send, name='api_direct_send'),
    path('direct/attachments/<int:message_id>/', direct_views.direct_attachment, name='direct_attachment'),
    path('api/presence/', direct_views.api_presence, name='api_presence'),
    path('api/classe/<int:classroom_id>/members/', direct_views.api_room_members, name='api_room_members'),
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
