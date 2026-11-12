import json
import mimetypes

from django.http import FileResponse, Http404, JsonResponse, HttpResponseForbidden
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST
from django.utils import timezone
from django.db.models import F

from accounts.decorators import login_required_simple
from classrooms.models import Classroom, ClassroomMember

from .models import (
    ClassChatRoom,
    ChatMessage,
    PrivateConversation,
    PrivateMessage,
)
from .permissions import get_edubac_user, user_can_access_classroom, classrooms_for_user


def _require_access(request, classroom_id):
    user = get_edubac_user(request)
    if not user:
        return None, None, JsonResponse({'error': 'Non authentifié'}, status=401)
    classroom = get_object_or_404(Classroom, pk=classroom_id)
    if not user_can_access_classroom(user, classroom):
        return user, classroom, JsonResponse(
            {'error': 'Accès refusé à cette conversation.'},
            status=403,
        )
    return user, classroom, None


def _room_payload(room, user):
    last = room.last_message()
    classroom = room.classroom
    members_count = classroom.members.count()
    if classroom.teacher_id:
        members_count += 1  # enseignant inclus dans le compteur affiché
    return {
        'classroom_id': classroom.pk,
        'name': classroom.name,
        'niveau': classroom.get_niveau_display(),
        'members_count': classroom.members.count(),
        'unread': room.unread_count_for(user),
        'last_message': (
            (last.body[:80] if last and last.body else '')
            or (('📎 ' + last.attachment_name) if last and last.attachment else '')
        ),
        'last_message_time': (
            last.created_at.strftime('%H:%M') if last else ''
        ),
        'last_message_at': last.created_at.isoformat() if last else '',
        'avatar_letter': (classroom.name[:1] or 'C').upper(),
    }


def _private_conversations_for(user):
    conversations = PrivateConversation.objects.select_related(
        'classroom', 'student', 'teacher',
    )
    if user.is_student():
        return conversations.filter(
            student=user,
            classroom__members__user=user,
            classroom__teacher_id=F('teacher_id'),
        )
    if user.is_teacher():
        return conversations.filter(
            teacher=user,
            classroom__teacher=user,
        )
    return conversations.none()


def _private_message_payload(message):
    sender = message.sender
    return {
        'id': message.pk,
        'body': message.body,
        'sender_id': sender.pk,
        'sender_name': sender.get_full_name() or sender.username,
        'created_at': message.created_at.isoformat(),
        'time_display': timezone.localtime(message.created_at).strftime('%d/%m/%Y %H:%M'),
        'is_read': message.read_at is not None,
        'is_voice': message.is_voice,
        'is_image': message.is_image,
        'attachment_url': (
            reverse('chat:private_attachment', args=[message.pk])
            if message.attachment else ''
        ),
        'attachment_name': message.attachment_name,
    }


@login_required_simple
def chat_home(request):
    """Liste des conversations + zone vide (ou première classe)."""
    user = get_edubac_user(request)
    classes = classrooms_for_user(user)
    rooms_data = []
    for c in classes:
        room = ClassChatRoom.get_or_create_for(c)
        rooms_data.append(_room_payload(room, user))
    rooms_data.sort(key=lambda r: r.get('last_message_at') or '', reverse=True)
    return render(request, 'chat/room.html', {
        'rooms': rooms_data,
        'active_classroom': None,
        'page_title': 'Prof-Étudiant Chat',
    })


@login_required_simple
def chat_room(request, classroom_id):
    user = get_edubac_user(request)
    classroom = get_object_or_404(Classroom, pk=classroom_id)
    if not user_can_access_classroom(user, classroom):
        from django.contrib import messages
        messages.error(request, 'Vous n\'avez pas accès à cette conversation.')
        return redirect('chat:home')

    room = ClassChatRoom.get_or_create_for(classroom)
    room.mark_read(user)

    classes = classrooms_for_user(user)
    rooms_data = []
    for c in classes:
        r = ClassChatRoom.get_or_create_for(c)
        rooms_data.append(_room_payload(r, user))
    rooms_data.sort(key=lambda r: r.get('last_message_at') or '', reverse=True)

    return render(request, 'chat/room.html', {
        'rooms': rooms_data,
        'active_classroom': classroom,
        'active_room': room,
        'members_count': classroom.members.count(),
        'page_title': f'Chat — {classroom.name}',
    })


@login_required_simple
@require_GET
def api_rooms(request):
    user = get_edubac_user(request)
    classes = classrooms_for_user(user)
    data = []
    for c in classes:
        room = ClassChatRoom.get_or_create_for(c)
        data.append(_room_payload(room, user))
    data.sort(key=lambda r: r.get('last_message_at') or '', reverse=True)
    total_unread = sum(r['unread'] for r in data)
    return JsonResponse({'rooms': data, 'total_unread': total_unread})


@login_required_simple
@require_GET
def api_messages(request, classroom_id):
    user, classroom, err = _require_access(request, classroom_id)
    if err:
        return err
    room = ClassChatRoom.get_or_create_for(classroom)

    after_id = request.GET.get('after_id')
    qs = room.messages.select_related('sender').order_by('created_at')
    if after_id:
        try:
            qs = qs.filter(pk__gt=int(after_id))
        except (TypeError, ValueError):
            pass
    else:
        # Derniers 100 messages au chargement
        qs = qs.order_by('-created_at')[:100]
        messages_list = list(reversed(list(qs)))
        room.mark_read(user)
        return JsonResponse({
            'messages': [m.to_dict() for m in messages_list],
            'classroom_id': classroom.pk,
            'classroom_name': classroom.name,
            'members_count': classroom.members.count(),
        })

    messages_list = list(qs[:50])
    if messages_list:
        room.mark_read(user)
    return JsonResponse({
        'messages': [m.to_dict() for m in messages_list],
        'classroom_id': classroom.pk,
    })


@login_required_simple
@require_GET
def attachment(request, message_id):
    message = get_object_or_404(
        ChatMessage.objects.select_related('room__classroom'),
        pk=message_id,
    )
    _, _, err = _require_access(request, message.room.classroom_id)
    if err:
        return err
    if not message.attachment:
        raise Http404
    try:
        handle = message.attachment.open('rb')
    except FileNotFoundError:
        raise Http404
    content_type = mimetypes.guess_type(message.attachment_name)[0]
    response = FileResponse(
        handle,
        content_type=content_type or 'application/octet-stream',
        filename=message.attachment_name,
    )
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@login_required_simple
@require_POST
def api_send(request, classroom_id):
    user, classroom, err = _require_access(request, classroom_id)
    if err:
        return err
    room = ClassChatRoom.get_or_create_for(classroom)

    # JSON ou multipart (fichier / image)
    content_type = (request.content_type or '')
    if 'multipart/form-data' in content_type or request.FILES:
        body = (request.POST.get('body') or '').strip()
        upload = request.FILES.get('attachment')
    else:
        try:
            payload = json.loads(request.body.decode('utf-8') or '{}')
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = request.POST
        body = (payload.get('body') or '').strip()
        upload = None

    is_voice = False
    if 'multipart/form-data' in content_type or request.FILES:
        is_voice = (request.POST.get('is_voice') or '') in ('1', 'true', 'True')
        reply_raw = request.POST.get('reply_to')
    else:
        reply_raw = payload.get('reply_to') if isinstance(payload, dict) else None

    reply_to = None
    if reply_raw:
        try:
            reply_to = ChatMessage.objects.get(pk=int(reply_raw), room=room)
        except (ChatMessage.DoesNotExist, TypeError, ValueError):
            reply_to = None

    if not body and not upload:
        return JsonResponse({'error': 'Message vide.'}, status=400)
    if len(body) > 4000:
        return JsonResponse({'error': 'Message trop long (max 4000).'}, status=400)

    if upload:
        if upload.size > 10 * 1024 * 1024:
            return JsonResponse({'error': 'Fichier trop volumineux (max 10 Mo).'}, status=400)
        allowed_ext = (
            '.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp',
            '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.txt', '.zip',
            '.webm', '.ogg', '.mp3', '.wav', '.m4a',
        )
        name_lower = (upload.name or '').lower()
        if not any(name_lower.endswith(ext) for ext in allowed_ext):
            # voice blobs sometimes have no extension
            if not is_voice:
                return JsonResponse({
                    'error': 'Type de fichier non autorisé.'
                }, status=400)
        if is_voice or any(name_lower.endswith(e) for e in ('.webm', '.ogg', '.mp3', '.wav', '.m4a')):
            is_voice = True

    msg = ChatMessage.objects.create(
        room=room,
        sender=user,
        body=body,
        attachment=upload if upload else None,
        reply_to=reply_to,
        is_voice=is_voice,
    )
    room.mark_read(user)

    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer
        layer = get_channel_layer()
        if layer:
            async_to_sync(layer.group_send)(
                f'chat_{classroom.pk}',
                {'type': 'chat.message', 'message': msg.to_dict()},
            )
    except Exception:
        pass

    return JsonResponse({'ok': True, 'message': msg.to_dict()})


@login_required_simple
@require_POST
def api_mark_read(request, classroom_id):
    user, classroom, err = _require_access(request, classroom_id)
    if err:
        return err
    room = ClassChatRoom.get_or_create_for(classroom)
    room.mark_read(user)
    return JsonResponse({'ok': True})


@login_required_simple
@require_GET
def api_unread_total(request):
    user = get_edubac_user(request)
    total = 0
    for c in classrooms_for_user(user):
        room = ClassChatRoom.get_or_create_for(c)
        total += room.unread_count_for(user)
    return JsonResponse({'total_unread': total})



@login_required_simple
@require_POST
def api_pin(request, classroom_id, message_id):
    """Épingler / désépingler — réservé à l'enseignant de la classe."""
    user, classroom, err = _require_access(request, classroom_id)
    if err:
        return err
    if getattr(user, 'role', None) != 'teacher' or classroom.teacher_id != user.id:
        return JsonResponse({'error': 'Seul le professeur peut épingler.'}, status=403)
    room = ClassChatRoom.get_or_create_for(classroom)
    try:
        msg = ChatMessage.objects.get(pk=message_id, room=room)
    except ChatMessage.DoesNotExist:
        return JsonResponse({'error': 'Message introuvable.'}, status=404)
    msg.is_pinned = not msg.is_pinned
    msg.save(update_fields=['is_pinned'])
    return JsonResponse({'ok': True, 'is_pinned': msg.is_pinned, 'message': msg.to_dict()})


@login_required_simple
def private_student_chat(request, classroom_id):
    """Ouvrir la conversation privée de l'élève avec le professeur de sa classe."""
    user = get_edubac_user(request)
    if not user.is_student():
        return HttpResponseForbidden('Cette conversation est réservée aux élèves de la classe.')
    membership = get_object_or_404(
        ClassroomMember.objects.select_related('classroom', 'classroom__teacher'),
        classroom_id=classroom_id,
        user=user,
    )
    classroom = membership.classroom
    if not classroom.teacher_id:
        from django.contrib import messages
        messages.error(request, 'Aucun professeur n’est associé à cette classe.')
        return redirect('classrooms:detail', pk=classroom.pk)
    conversation, _ = PrivateConversation.objects.get_or_create(
        classroom=classroom,
        student=user,
        teacher=classroom.teacher,
    )
    return redirect('chat:private_room', conversation_id=conversation.pk)


@login_required_simple
def private_inbox(request):
    """Boîte des conversations individuelles du professeur."""
    user = get_edubac_user(request)
    if not user.is_teacher():
        return HttpResponseForbidden('Cette boîte est réservée aux professeurs.')
    conversations = list(
        _private_conversations_for(user).order_by('-updated_at')[:100]
    )
    for conversation in conversations:
        conversation.latest_message = conversation.last_message()
    return render(request, 'chat/private_inbox.html', {
        'conversations': conversations,
        'page_title': 'Consultations individuelles',
    })


@login_required_simple
def private_room(request, conversation_id):
    user = get_edubac_user(request)
    conversation = get_object_or_404(
        _private_conversations_for(user),
        pk=conversation_id,
    )
    contact = (
        conversation.teacher
        if user.pk == conversation.student_id
        else conversation.student
    )
    return render(request, 'chat/private_room.html', {
        'conversation': conversation,
        'contact': contact,
        'is_teacher': user.pk == conversation.teacher_id,
        'page_title': 'Consultation avec le professeur',
    })


@login_required_simple
@require_GET
def api_private_messages(request, conversation_id):
    user = get_edubac_user(request)
    conversation = get_object_or_404(
        _private_conversations_for(user),
        pk=conversation_id,
    )
    conversation.messages.filter(
        read_at__isnull=True,
    ).exclude(sender=user).update(read_at=timezone.now())
    messages_qs = conversation.messages.select_related('sender').order_by('created_at')
    after_id = request.GET.get('after_id')
    if after_id:
        try:
            after_id = int(after_id)
        except (TypeError, ValueError):
            return JsonResponse({'error': 'Identifiant de message invalide.'}, status=400)
        if after_id < 0:
            return JsonResponse({'error': 'Identifiant de message invalide.'}, status=400)
        messages_qs = messages_qs.filter(pk__gt=after_id)[:50]
    else:
        messages_qs = messages_qs.order_by('-created_at')[:100]
        messages_qs = reversed(list(messages_qs))
    return JsonResponse({
        'messages': [_private_message_payload(message) for message in messages_qs],
        'read_ids': list(
            conversation.messages.filter(
                sender=user,
                read_at__isnull=False,
            ).order_by('-created_at').values_list('pk', flat=True)[:100]
        ),
    })


@login_required_simple
@require_POST
def api_private_send(request, conversation_id):
    user = get_edubac_user(request)
    conversation = get_object_or_404(
        _private_conversations_for(user),
        pk=conversation_id,
    )
    upload = None
    is_voice = False
    if request.FILES or 'multipart/form-data' in (request.content_type or ''):
        body = (request.POST.get('body') or '').strip()
        upload = request.FILES.get('attachment')
        is_voice = (request.POST.get('is_voice') or '').lower() in {'1', 'true'}
    else:
        try:
            payload = json.loads(request.body.decode('utf-8') or '{}')
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse({'error': 'Requête invalide.'}, status=400)
        if not isinstance(payload, dict) or not isinstance(payload.get('body', ''), str):
            return JsonResponse({'error': 'Requête invalide.'}, status=400)
        body = payload.get('body', '').strip()
    if not body and not upload:
        return JsonResponse({'error': 'Écrivez un message.'}, status=400)
    if len(body) > 4000:
        return JsonResponse({'error': 'Message trop long (4 000 caractères maximum).'}, status=400)
    attachment_name = ''
    if upload:
        if upload.size > 10 * 1024 * 1024:
            return JsonResponse({'error': 'Fichier trop volumineux (maximum 10 Mo).'}, status=400)
        from pathlib import Path
        original_name = (upload.name or '').replace('\\', '/')
        attachment_name = Path(original_name).name[:255]
        extension = Path(attachment_name).suffix.lower()
        allowed_extensions = {
            '.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp',
            '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.txt', '.zip',
            '.webm', '.ogg', '.mp3', '.wav', '.m4a', '.aac',
        }
        if extension not in allowed_extensions:
            return JsonResponse({'error': 'Type de fichier non autorisé.'}, status=400)
        is_voice = is_voice or extension in {
            '.webm', '.ogg', '.mp3', '.wav', '.m4a', '.aac',
        }
    message = PrivateMessage(
        conversation=conversation,
        sender=user,
        body=body,
        attachment_name=attachment_name,
        is_voice=is_voice,
    )
    if upload:
        message.attachment = upload
    message.save()
    conversation.save(update_fields=['updated_at'])
    return JsonResponse({'ok': True, 'message': _private_message_payload(message)})


@login_required_simple
@require_GET
def private_attachment(request, message_id):
    user = get_edubac_user(request)
    message = get_object_or_404(
        PrivateMessage.objects.select_related('conversation'),
        pk=message_id,
        conversation__in=_private_conversations_for(user),
    )
    if not message.attachment:
        raise Http404
    try:
        handle = message.attachment.open('rb')
    except FileNotFoundError:
        raise Http404
    content_type = mimetypes.guess_type(message.attachment_name)[0]
    inline = message.is_image or message.is_voice
    response = FileResponse(
        handle,
        content_type=content_type or 'application/octet-stream',
        as_attachment=not inline,
        filename=message.attachment_name or 'piece-jointe',
    )
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
