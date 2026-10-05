from django.contrib import admin
from .models import ClassChatRoom, ChatMessage, ChatReadState


@admin.register(ClassChatRoom)
class ClassChatRoomAdmin(admin.ModelAdmin):
    list_display = ('classroom', 'created_at')
    search_fields = ('classroom__name',)


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ('room', 'sender', 'body_short', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('body', 'sender__username')

    def body_short(self, obj):
        return obj.body[:60]
    body_short.short_description = 'Message'


@admin.register(ChatReadState)
class ChatReadStateAdmin(admin.ModelAdmin):
    list_display = ('room', 'user', 'last_read_at')
