"""Badge non lus pour Prof-Étudiant Chat."""


def chat_unread(request):
    ctx = {'chat_unread_total': 0}
    user = getattr(request, 'edubac_user', None) or getattr(request, 'user', None)
    if not user or not getattr(user, 'is_authenticated', False):
        return ctx
    try:
        from django.db.models import F
        from chat.permissions import classrooms_for_user
        from chat.permissions import direct_conversations_for, user_can_access_direct_conversation
        from chat.models import (
            ClassChatRoom,
            DirectMessage,
            PrivateConversation,
            PrivateMessage,
        )
        total = 0
        for c in classrooms_for_user(user):
            room = ClassChatRoom.get_or_create_for(c)
            total += room.unread_count_for(user)
        direct_ids = [
            conversation.pk
            for conversation in direct_conversations_for(user)
            if user_can_access_direct_conversation(user, conversation)
        ]
        if direct_ids:
            total += DirectMessage.objects.filter(
                conversation_id__in=direct_ids,
                read_at__isnull=True,
            ).exclude(sender=user).count()
        if user.is_student():
            private_conversations = PrivateConversation.objects.filter(
                student=user,
                classroom__members__user=user,
                classroom__teacher_id=F('teacher_id'),
            )
        elif user.is_teacher():
            private_conversations = PrivateConversation.objects.filter(
                teacher=user,
                classroom__teacher=user,
            )
        else:
            private_conversations = PrivateConversation.objects.none()
        total += PrivateMessage.objects.filter(
            conversation__in=private_conversations,
            read_at__isnull=True,
        ).exclude(sender=user).count()
        ctx['chat_unread_total'] = total
    except Exception:
        pass
    return ctx
