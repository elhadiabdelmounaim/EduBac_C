"""Badge non lus pour Prof-Étudiant Chat."""


def chat_unread(request):
    ctx = {'chat_unread_total': 0}
    user = getattr(request, 'edubac_user', None) or getattr(request, 'user', None)
    if not user or not getattr(user, 'is_authenticated', False):
        return ctx
    try:
        from chat.permissions import classrooms_for_user
        from chat.models import ClassChatRoom
        total = 0
        for c in classrooms_for_user(user):
            room = ClassChatRoom.get_or_create_for(c)
            total += room.unread_count_for(user)
        ctx['chat_unread_total'] = total
    except Exception:
        pass
    return ctx
