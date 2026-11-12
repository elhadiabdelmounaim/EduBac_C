import json
import mimetypes
from pathlib import Path
from datetime import timedelta

from django.http import FileResponse, Http404, JsonResponse, HttpResponseForbidden
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST
from django.utils import timezone
from django.db.models import F, Q
from django.contrib.auth import get_user_model

from accounts.decorators import login_required_simple
from classrooms.models import Classroom, ClassroomMember
from accounts.models import User

from .models import (
    ClassChatRoom,
    ChatMessage,
    ChatPresence,
    DirectConversation,
    DirectMessage,
    PrivateConversation,
    PrivateMessage,
)
from .permissions import (
    classrooms_for_user,
    direct_conversation_start_context,
    direct_conversations_for,
    get_edubac_user,
    is_platform_admin,
    platform_admin_user,
    user_can_access_classroom,
    user_can_access_direct_conversation,
)


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
        'members_count': members_count,
        'unread': room.unread_count_for(user),
        'last_message': (
            (last.body[:80] if last and last.body else '')
            or (('📎 ' + last.attachment_name) if last and last.attachment else '')
        ),
        'last_message_time': (
            last.created_at.strftime('%H:%M') if last else ''
        ),
        'last_message_at': last.created_at.isoformat() if last else '',
        'last_message_date': (
            timezone.localtime(last.created_at).strftime('%d/%m/%Y')
            if last else ''
        ),
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


def _is_online(user, now=None):
    if not user:
        return False
    now = now or timezone.now()
    return ChatPresence.objects.filter(
        user=user,
        last_seen_at__gte=now - timedelta(seconds=90),
    ).exists()


def _direct_conversation_payload(conversation, user, now=None):
    contact = conversation.other_participant(user)
    if not contact:
        return None
    last = conversation.last_message()
    student = contact if contact.is_student() else (user if user.is_student() else None)
    classroom = conversation.classroom
    if student and (
        not classroom
        or not classroom.is_active
        or not ClassroomMember.objects.filter(
            classroom=classroom,
            user=student,
        ).exists()
    ):
        shared_classes = Classroom.objects.filter(
            members__user=student,
            is_active=True,
        )
        if contact.is_student():
            shared_classes = shared_classes.filter(members__user=contact)
        classroom = shared_classes.order_by('name').first()
    name = 'Admin EduBac' if is_platform_admin(contact) else (
        contact.get_full_name() or contact.username
    )
    class_label = (
        f'{classroom.name} · {classroom.get_niveau_display()}'
        if classroom else ('Administration EduBac' if is_platform_admin(contact) else '')
    )
    return {
        'id': conversation.pk,
        'url': reverse('chat:direct_room', args=[conversation.pk]),
        'name': name,
        'subtitle': class_label,
        'kind': 'direct',
        'last_message': (
            (last.body[:100] if last and last.body else '')
            or (('📎 ' + last.attachment_name) if last and last.attachment else '')
        ),
        'last_message_time': (
            timezone.localtime(last.created_at).strftime('%d/%m %H:%M')
            if last else ''
        ),
        'last_message_at': last.created_at.isoformat() if last else '',
        'unread': conversation.unread_count_for(user),
        'is_online': _is_online(contact, now),
        'avatar_letter': (name[:1] or '?').upper(),
        'search_text': ' '.join(filter(None, [
            name,
            contact.username,
            class_label,
            classroom.name if classroom else '',
        ])).lower(),
        'classroom_id': classroom.pk if classroom else '',
    }


def _consultation_payload(conversation, user, now=None):
    contact = (
        conversation.teacher
        if user.pk == conversation.student_id
        else conversation.student
    )
    last = conversation.last_message()
    name = contact.get_full_name() or contact.username
    classroom = conversation.classroom
    subtitle = f'{classroom.name} · {classroom.get_niveau_display()}'
    return {
        'id': conversation.pk,
        'url': reverse('chat:private_room', args=[conversation.pk]),
        'name': name,
        'subtitle': subtitle,
        'kind': 'consultation',
        'last_message': (
            (last.body[:100] if last and last.body else '')
            or (('📎 ' + last.attachment_name) if last and last.attachment else '')
        ),
        'last_message_time': (
            timezone.localtime(last.created_at).strftime('%d/%m %H:%M')
            if last else ''
        ),
        'last_message_at': last.created_at.isoformat() if last else '',
        'unread': conversation.messages.filter(
            read_at__isnull=True,
        ).exclude(sender=user).count(),
        'is_online': _is_online(contact, now),
        'avatar_letter': (name[:1] or '?').upper(),
        'search_text': ' '.join(filter(None, [
            name,
            contact.username,
            classroom.name,
            classroom.get_niveau_display(),
        ])).lower(),
        'classroom_id': classroom.pk,
    }


def _messaging_context(user, active_tab='groups'):
    now = timezone.now()
    classrooms = list(classrooms_for_user(user))
    rooms = [
        _room_payload(ClassChatRoom.get_or_create_for(classroom), user)
        for classroom in classrooms
    ]
    if user.is_student():
        admin = platform_admin_user()
        if admin and admin.pk != user.pk:
            DirectConversation.get_or_create_for(user, admin)

    conversations = []
    for conversation in direct_conversations_for(user):
        if user_can_access_direct_conversation(user, conversation):
            item = _direct_conversation_payload(conversation, user, now)
            if item:
                conversations.append(item)
    for conversation in _private_conversations_for(user):
        conversations.append(_consultation_payload(conversation, user, now))
    conversations.sort(key=lambda item: item['last_message_at'], reverse=True)
    return {
        'rooms': rooms,
        'conversations': conversations,
        'class_options': [{'id': classroom.pk, 'name': classroom.name} for classroom in classrooms],
        'is_admin': is_platform_admin(user),
        'is_teacher': user.is_teacher(),
        'is_student': user.is_student(),
        'active_tab': active_tab,
        'contacts_url': reverse('chat:api_direct_contacts'),
        'start_url': reverse('chat:api_direct_start'),
        'presence_url': reverse('chat:api_presence'),
        'page_title': 'Messagerie EduBac',
    }


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
    """Boîte de messagerie unifiée, limitée aux conversations autorisées."""
    user = get_edubac_user(request)
    return render(request, 'chat/messaging_home.html', _messaging_context(user))


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
    online_ids = set(ChatPresence.objects.filter(
        last_seen_at__gte=timezone.now() - timedelta(seconds=90),
    ).values_list('user_id', flat=True))
    online_count = classroom.members.filter(user_id__in=online_ids).count()
    if classroom.teacher_id in online_ids:
        online_count += 1

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
        'members_count': classroom.members.count() + (1 if classroom.teacher_id else 0),
        'online_count': online_count,
        'presence_url': reverse('chat:api_presence'),
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
        announcement_raw = request.POST.get('is_announcement')
    else:
        try:
            payload = json.loads(request.body.decode('utf-8') or '{}')
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = request.POST
        if (
            not hasattr(payload, 'get')
            or not isinstance(payload.get('body', ''), str)
        ):
            return JsonResponse({'error': 'Requête invalide.'}, status=400)
        body = (payload.get('body') or '').strip()
        upload = None
        announcement_raw = payload.get('is_announcement') if isinstance(payload, dict) else None

    is_voice = False
    is_announcement = str(announcement_raw or '').lower() in {'1', 'true', 'on', 'yes'}
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
    if is_announcement and not (
        is_platform_admin(user)
        or (user.is_teacher() and classroom.teacher_id == user.pk)
    ):
        return JsonResponse(
            {'error': 'Seuls le professeur de la classe et l’administration peuvent publier une annonce.'},
            status=403,
        )

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
        is_announcement=is_announcement,
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
    from .context_processors import chat_unread

    return JsonResponse({
        'total_unread': chat_unread(request).get('chat_unread_total', 0),
    })



@login_required_simple
@require_POST
def api_pin(request, classroom_id, message_id):
    """Épingler / désépingler — réservé à l'enseignant de la classe."""
    user, classroom, err = _require_access(request, classroom_id)
    if err:
        return err
    if not (
        is_platform_admin(user)
        or (user.is_teacher() and classroom.teacher_id == user.id)
    ):
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
    """Compatibilité avec l'ancien lien vers les conversations individuelles."""
    user = get_edubac_user(request)
    if not (user.is_teacher() or is_platform_admin(user)):
        return HttpResponseForbidden(
            'Cette boîte de réception est réservée à l’équipe pédagogique.'
        )
    return render(
        request,
        'chat/messaging_home.html',
        _messaging_context(user, active_tab='individuals'),
    )


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
        'contact_display_name': contact.get_full_name() or contact.username,
        'conversation_kind': 'consultation',
        'is_teacher': user.pk == conversation.teacher_id,
        'conversation_subtitle': (
            f'{conversation.classroom.name} · '
            f'{conversation.classroom.get_niveau_display()}'
        ),
        'messages_url': reverse('chat:api_private_messages', args=[conversation.pk]),
        'send_url': reverse('chat:api_private_send', args=[conversation.pk]),
        'presence_url': reverse('chat:api_presence'),
        'back_url': (
            reverse('chat:home') + '?tab=individuals'
            if user.pk == conversation.teacher_id
            else reverse('classrooms:detail', args=[conversation.classroom_id])
        ),
        'page_title': 'Consultation avec le professeur',
    })


@login_required_simple
def direct_room(request, conversation_id):
    user = get_edubac_user(request)
    conversation = get_object_or_404(
        direct_conversations_for(user),
        pk=conversation_id,
    )
    if not user_can_access_direct_conversation(user, conversation):
        return HttpResponseForbidden('Accès refusé à cette conversation.')
    contact = conversation.other_participant(user)
    contact_name = 'Admin EduBac' if is_platform_admin(contact) else (
        contact.get_full_name() or contact.username
    )
    return render(request, 'chat/private_room.html', {
        'conversation': conversation,
        'contact': contact,
        'contact_display_name': contact_name,
        'conversation_kind': 'direct',
        'is_teacher': user.is_teacher(),
        'conversation_subtitle': (
            f'{conversation.classroom.name} · '
            f'{conversation.classroom.get_niveau_display()}'
            if conversation.classroom_id else 'Conversation privée'
        ),
        'messages_url': reverse('chat:api_direct_messages', args=[conversation.pk]),
        'send_url': reverse('chat:api_direct_send', args=[conversation.pk]),
        'presence_url': reverse('chat:api_presence'),
        'back_url': reverse('chat:home') + '?tab=individuals',
        'page_title': (
            'Conversation avec ' + contact_name
        ),
    })


@login_required_simple
@require_GET
def api_private_messages(request, conversation_id):
    user = get_edubac_user(request)
    conversation = _private_conversations_for(user).filter(pk=conversation_id).first()
    if conversation is None:
        return JsonResponse(
            {'error': 'Cette conversation n’est plus accessible.'},
            status=404,
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
    conversation = _private_conversations_for(user).filter(pk=conversation_id).first()
    if conversation is None:
        return JsonResponse(
            {'error': 'Cette conversation n’est plus accessible.'},
            status=404,
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
