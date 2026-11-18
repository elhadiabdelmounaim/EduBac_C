"""Badge « messages non lus » affiché sur toutes les pages.

Exécuté à chaque rendu : trois requêtes agrégées, sans boucle par classe ou
par conversation et sans aucune écriture en base.
"""
import logging

from django.db.models import F, OuterRef, Q, Subquery

logger = logging.getLogger(__name__)


def unread_total(user):
    from chat.models import (
        ChatMessage,
        ChatReadState,
        DirectMessage,
        PrivateConversation,
        PrivateMessage,
    )
    from chat.permissions import accessible_direct_conversations, classrooms_for_user

    class_ids = classrooms_for_user(user).values('pk')
    last_read = ChatReadState.objects.filter(
        room=OuterRef('room'), user=user,
    ).values('last_read_at')[:1]
    total = (
        ChatMessage.objects.filter(room__classroom__in=class_ids, deleted_at__isnull=True)
        .exclude(sender=user)
        .annotate(last_read=Subquery(last_read))
        .filter(Q(last_read__isnull=True) | Q(created_at__gt=F('last_read')))
        .count()
    )
    total += DirectMessage.objects.filter(
        conversation__in=accessible_direct_conversations(user).values('pk'),
        read_at__isnull=True,
        deleted_at__isnull=True,
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
        conversation__in=private_conversations.values('pk'),
        read_at__isnull=True,
        deleted_at__isnull=True,
    ).exclude(sender=user).count()
    return total


def chat_unread(request):
    ctx = {'chat_unread_total': 0}
    user = getattr(request, 'edubac_user', None) or getattr(request, 'user', None)
    if not user or not getattr(user, 'is_authenticated', False):
        return ctx
    try:
        ctx['chat_unread_total'] = unread_total(user)
    except Exception:
        logger.exception('chat unread count failed user=%s', user.pk)
    return ctx
