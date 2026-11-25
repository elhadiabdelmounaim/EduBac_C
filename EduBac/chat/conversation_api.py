"""Logique commune aux API des consultations et des messages individuels."""
import json

from django.http import JsonResponse
from django.utils import timezone

from . import realtime
from .attachments import AttachmentError, validate_upload
from .payloads import parse_since

MAX_BODY = 4000


def _optional_id(value):
    if value in (None, ''):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError
    if number <= 0:
        raise ValueError
    return number


def parse_send_request(request):
    """Lit un envoi JSON ou multipart. Retourne un dict, ou une JsonResponse d'erreur."""
    upload = None
    is_voice = False
    if request.FILES or 'multipart/form-data' in (request.content_type or ''):
        data = request.POST
        upload = request.FILES.get('attachment')
        is_voice = (data.get('is_voice') or '').lower() in {'1', 'true'}
    else:
        try:
            data = json.loads(request.body.decode('utf-8') or '{}')
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse({'error': 'Requête invalide.'}, status=400)
        if not isinstance(data, dict) or not isinstance(data.get('body', ''), str):
            return JsonResponse({'error': 'Requête invalide.'}, status=400)
    body = (data.get('body') or '').strip()
    if not body and not upload:
        return JsonResponse({'error': 'Écrivez un message.'}, status=400)
    if len(body) > MAX_BODY:
        return JsonResponse({'error': 'Message trop long (4 000 caractères maximum).'}, status=400)
    try:
        lesson_id = _optional_id(data.get('lesson_id'))
        question_id = _optional_id(data.get('question_id'))
    except ValueError:
        return JsonResponse({'error': 'Contexte du message invalide.'}, status=400)
    try:
        reply_to_id = _optional_id(data.get('reply_to'))
    except ValueError:
        reply_to_id = None
    attachment_name = ''
    if upload:
        try:
            attachment_name, is_voice = validate_upload(upload, is_voice=is_voice)
        except AttachmentError as exc:
            return JsonResponse({'error': str(exc)}, status=400)
    return {
        'body': body,
        'upload': upload,
        'attachment_name': attachment_name,
        'is_voice': is_voice,
        'lesson_id': lesson_id,
        'question_id': question_id,
        'reply_to_id': reply_to_id,
    }


def resolve_reply(conversation, reply_to_id):
    """Message cité, seulement s'il appartient à la même conversation et n'est pas supprimé."""
    if not reply_to_id:
        return None
    return conversation.messages.filter(pk=reply_to_id, deleted_at__isnull=True).first()


def conversation_messages_response(request, user, conversation, *, payload, kind, select=('sender',)):
    select = (*select, 'reply_to__sender')
    """Messages d'une conversation : chargement initial, nouveautés et modifications."""
    server_time = timezone.now()
    marked = conversation.messages.filter(
        read_at__isnull=True,
    ).exclude(sender=user).update(read_at=server_time)
    if marked:
        realtime.conversation_changed(kind, conversation.pk, event='read')
    # Ouvrir la conversation vaut lecture de sa notification regroupée.
    from notifications.models import Notification
    from notifications.services import conversation_group_key
    Notification.mark_group_read(user, conversation_group_key(kind, conversation.pk))

    messages_qs = conversation.messages.select_related(*select).order_by('created_at')
    after_id = request.GET.get('after_id')
    if after_id:
        try:
            after_id = int(after_id)
        except (TypeError, ValueError):
            return JsonResponse({'error': 'Identifiant de message invalide.'}, status=400)
        if after_id < 0:
            return JsonResponse({'error': 'Identifiant de message invalide.'}, status=400)
        messages = list(messages_qs.filter(pk__gt=after_id)[:50])
        since = parse_since(request.GET.get('since'))
        if since:
            messages = list(
                messages_qs.filter(pk__lte=after_id, updated_at__gt=since)[:100]
            ) + messages
    else:
        messages = list(reversed(list(messages_qs.order_by('-created_at')[:100])))
    from .reactions import charger
    charger(kind, messages)
    return JsonResponse({
        'messages': [payload(message, user) for message in messages],
        'read_ids': list(
            conversation.messages.filter(
                sender=user,
                read_at__isnull=False,
            ).order_by('-created_at').values_list('pk', flat=True)[:100]
        ),
        'server_time': server_time.isoformat(),
    })
