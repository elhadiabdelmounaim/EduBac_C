import json
from datetime import timedelta

from django.http import JsonResponse, HttpResponseForbidden
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST
from django.utils import timezone
from django.db.models import F, Q
from django.contrib.auth import get_user_model

from accounts.decorators import login_required_simple
from classrooms.models import Classroom, ClassroomMember
from accounts.models import User

from . import realtime
from .attachments import AttachmentError, serve_attachment, validate_upload
from .conversation_api import conversation_messages_response, parse_send_request
from .models import (
    EDIT_WINDOW_SECONDS,
    ClassChatRoom,
    ChatBlock,
    ChatMessage,
    ChatPresence,
    DirectConversation,
    PrivateConversation,
    PrivateMessage,
)
from .payloads import conversation_message_payload, parse_since
from .permissions import (
    accessible_direct_conversations,
    can_moderate_classroom,
    class_post_restriction,
    classrooms_for_user,
    direct_conversations_for,
    get_edubac_user,
    is_platform_admin,
    platform_admin_user,
    student_quiet_hours_restriction,
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


def _last_message_preview(last, user):
    """Aperçu du dernier message pour la liste des conversations."""
    if not last:
        return ''
    if last.body:
        text = last.body[:100]
    elif last.is_voice:
        text = '🎤 Message vocal'
    elif last.attachment and last.is_image:
        text = '📷 Photo'
    elif last.attachment:
        text = '📎 ' + (last.attachment_name or 'Fichier')
    else:
        text = ''
    if text and user and last.sender_id == user.pk:
        return 'Vous : ' + text
    return text


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
        'last_message': _last_message_preview(last, user),
        'last_message_time': (
            timezone.localtime(last.created_at).strftime('%H:%M') if last else ''
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
        'last_message': _last_message_preview(last, user),
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
        'last_message': _last_message_preview(last, user),
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
    for conversation in accessible_direct_conversations(user):
        item = _direct_conversation_payload(conversation, user, now)
        if item:
            conversations.append(item)
    for conversation in _private_conversations_for(user):
        conversations.append(_consultation_payload(conversation, user, now))
    conversations.sort(key=lambda item: item['last_message_at'], reverse=True)
    rooms.sort(key=lambda item: item['last_message_at'], reverse=True)
    # Liste unique (classes et conversations privées) triée par activité.
    threads = [
        {**room, 'kind': 'class', 'id': room['classroom_id'],
         'url': reverse('chat:room', args=[room['classroom_id']]),
         'subtitle': room['niveau']}
        for room in rooms
    ] + conversations
    threads.sort(key=lambda item: item['last_message_at'] or '', reverse=True)
    return {
        'rooms': rooms,
        'conversations': conversations,
        'threads': threads,
        'unread_threads': sum(1 for item in threads if item['unread']),
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


def _private_message_payload(message, user=None):
    return conversation_message_payload(message, user, 'chat:private_attachment')


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

    return render(request, 'chat/room.html', {
        **_messaging_context(user),
        'active_thread': f'class-{classroom.pk}',
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
    server_time = timezone.now()

    after_id = request.GET.get('after_id')
    qs = room.messages.select_related(
        'sender', 'reply_to__sender', 'whiteboard_share',
    ).order_by('created_at')
    if after_id:
        try:
            after_id = int(after_id)
        except (TypeError, ValueError):
            return JsonResponse({'error': 'Identifiant de message invalide.'}, status=400)
        messages_list = list(qs.filter(pk__gt=after_id)[:50])
        # Messages déjà affichés qui ont été modifiés, supprimés ou épinglés depuis.
        since = parse_since(request.GET.get('since'))
        if since:
            messages_list = list(
                qs.filter(pk__lte=after_id, updated_at__gt=since)[:100]
            ) + messages_list
        extra = {}
    else:
        # Derniers 100 messages au chargement
        messages_list = list(reversed(list(qs.order_by('-created_at')[:100])))
        extra = {
            'classroom_name': classroom.name,
            'members_count': classroom.members.count(),
        }
    return JsonResponse({
        'messages': [m.to_dict(user) for m in messages_list],
        'classroom_id': classroom.pk,
        'server_time': server_time.isoformat(),
        'room': _room_state(room, user),
        **extra,
    })


def _room_state(room, user):
    """Ce que l'utilisateur peut faire dans le salon, pour adapter l'interface."""
    restriction = class_post_restriction(user, room)
    return {
        'can_post': not restriction,
        'restriction': restriction,
        'can_moderate': can_moderate_classroom(user, room.classroom),
        'is_locked': room.is_locked,
        'allow_student_direct': room.allow_student_direct,
        'quiet_hours_start': room.quiet_hours_start.strftime('%H:%M') if room.quiet_hours_start else '',
        'quiet_hours_end': room.quiet_hours_end.strftime('%H:%M') if room.quiet_hours_end else '',
        'edit_window_seconds': EDIT_WINDOW_SECONDS,
    }


@login_required_simple
@require_GET
def attachment(request, message_id):
    message = get_object_or_404(
        ChatMessage.objects.select_related('room__classroom'),
        pk=message_id,
        deleted_at__isnull=True,
    )
    _, _, err = _require_access(request, message.room.classroom_id)
    if err:
        return err
    return serve_attachment(
        message.attachment, message.attachment_name, legacy_media_fallback=True,
    )


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
    restriction = class_post_restriction(user, room)
    if restriction:
        return JsonResponse({'error': restriction}, status=403)
    if is_announcement and not can_moderate_classroom(user, classroom):
        return JsonResponse(
            {'error': 'Seuls le professeur de la classe et l’administration peuvent publier une annonce.'},
            status=403,
        )

    attachment_name = ''
    if upload:
        try:
            attachment_name, is_voice = validate_upload(upload, is_voice=is_voice)
        except AttachmentError as exc:
            return JsonResponse({'error': str(exc)}, status=400)
        upload.name = attachment_name

    msg = ChatMessage.objects.create(
        room=room,
        sender=user,
        body=body,
        attachment=upload if upload else None,
        reply_to=reply_to if reply_to and not reply_to.is_deleted else None,
        is_voice=is_voice,
        is_announcement=is_announcement,
    )
    room.mark_read(user)
    realtime.class_message(classroom.pk, msg)
    if is_announcement:
        from notifications.services import notify_class_announcement
        notify_class_announcement(msg)
    else:
        _push_class_message(classroom, msg, user)
    return JsonResponse({'ok': True, 'message': msg.to_dict(user)})


def _push_class_message(classroom, message, sender):
    """Message du salon : notification sur le téléphone des membres (une par salon, remplacée)."""
    try:
        from notifications.models import NotificationPreference
        from notifications.push import is_configured, push_to_users
        if not is_configured():
            return
        member_ids = set(classroom.members.values_list('user_id', flat=True))
        if classroom.teacher_id:
            member_ids.add(classroom.teacher_id)
        member_ids.discard(sender.pk)
        members = list(User.objects.filter(pk__in=member_ids, is_active=True))
        muted = NotificationPreference.muted_user_ids(members, 'message')
        body = message.body[:160] if message.body else ('🎤 Message vocal' if message.is_voice else '📎 Pièce jointe')
        push_to_users(
            [m.pk for m in members if m.pk not in muted],
            title=classroom.name,
            body=f'{sender.get_full_name() or sender.username} : {body}',
            url=reverse('chat:room', args=[classroom.pk]),
            tag=f'chat-class-{classroom.pk}',
        )
    except Exception:
        import logging
        logging.getLogger(__name__).warning('class message push failed', exc_info=True)


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
    if not can_moderate_classroom(user, classroom):
        return JsonResponse({'error': 'Seul le professeur peut épingler.'}, status=403)
    room = ClassChatRoom.get_or_create_for(classroom)
    try:
        msg = ChatMessage.objects.get(pk=message_id, room=room)
    except ChatMessage.DoesNotExist:
        return JsonResponse({'error': 'Message introuvable.'}, status=404)
    if msg.is_deleted:
        return JsonResponse({'error': 'Ce message a été supprimé.'}, status=400)
    msg.is_pinned = not msg.is_pinned
    msg.touch('is_pinned')
    realtime.class_update(classroom.pk, msg)
    return JsonResponse({'ok': True, 'is_pinned': msg.is_pinned, 'message': msg.to_dict(user)})


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
    return redirect(
        reverse('chat:private_room', args=[conversation.pk]) + _context_query(request)
    )


def _context_query(request):
    """Conserve ?question= / ?lesson= pour pré-remplir le contexte d'une consultation."""
    for key in ('question', 'lesson'):
        value = (request.GET.get(key) or '').strip()
        if value.isdecimal():
            return f'?{key}={value}'
    return ''


@login_required_simple
def teacher_consult_student(request, student_id):
    """Professeur : ouvrir la consultation avec un élève de ses classes."""
    user = get_edubac_user(request)
    if not user.is_teacher():
        return HttpResponseForbidden('Réservé à l’équipe pédagogique.')
    student = get_object_or_404(User, pk=student_id, role='student')
    memberships = ClassroomMember.objects.filter(
        user=student, classroom__is_active=True,
    ).select_related('classroom')
    if not is_platform_admin(user):
        memberships = memberships.filter(classroom__teacher=user)
    membership = memberships.exclude(classroom__teacher__isnull=True).first()
    if membership is None:
        from django.contrib import messages
        messages.error(request, 'Cet élève ne fait partie d’aucune de vos classes actives.')
        return redirect('quizzes:student_results')
    conversation, _ = PrivateConversation.objects.get_or_create(
        classroom=membership.classroom,
        student=student,
        teacher=membership.classroom.teacher,
    )
    if conversation.teacher_id != user.pk:
        # Administration : la consultation appartient au professeur de la classe.
        from django.contrib import messages
        messages.info(request, 'Cette consultation est gérée par le professeur de la classe.')
        return redirect('chat:home')
    return redirect(
        reverse('chat:private_room', args=[conversation.pk]) + _context_query(request)
    )


def _consultation_context_options(conversation):
    """Leçons du niveau et questions récemment ratées, pour lier un message."""
    from education.models import Lesson
    from quizzes.models import StudentAnswer

    lessons = list(
        Lesson.objects.filter(course__niveau=conversation.classroom.niveau)
        .order_by('course__order', 'order')
        .values('pk', 'title')[:80]
    )
    wrong = (
        StudentAnswer.objects.filter(
            attempt__student=conversation.student,
            attempt__submitted_at__isnull=False,
            is_correct=False,
        )
        .select_related('question__quiz')
        .order_by('-attempt__submitted_at', 'question__order')[:15]
    )
    questions = []
    seen = set()
    for answer in wrong:
        question = answer.question
        if question.pk in seen:
            continue
        seen.add(question.pk)
        questions.append({
            'pk': question.pk,
            'label': f'Q{question.order} — {question.quiz.title}',
        })
    return {'lessons': lessons, 'questions': questions}


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
        **_messaging_context(user),
        'active_thread': f'consultation-{conversation.pk}',
        'contact_online': _is_online(contact),
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
        'ws_path': f'/ws/chat/consultation/{conversation.pk}/',
        'ai_draft_url': (
            reverse('chat:api_ai_draft', args=[conversation.pk])
            if user.pk == conversation.teacher_id else ''
        ),
        'context_options': _consultation_context_options(conversation),
        'initial_context': _initial_context(request, user, conversation),
        'message_kind': 'consultation',
        'page_title': 'Consultation avec le professeur',
    })


def _initial_context(request, user, conversation):
    parsed = {'lesson_id': None, 'question_id': None}
    for key in ('question', 'lesson'):
        value = (request.GET.get(key) or '').strip()
        if value.isdecimal():
            parsed[f'{key}_id'] = int(value)
            break
    if not (parsed['lesson_id'] or parsed['question_id']):
        return None
    lesson, question, error = _resolve_message_context(user, conversation, parsed)
    if error:
        return None
    if question:
        return {'kind': 'question', 'id': question.pk,
                'label': f'Question {question.order} — {question.quiz.title}'}
    return {'kind': 'lesson', 'id': lesson.pk, 'label': f'Leçon : {lesson.title}'}


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
        **_messaging_context(user),
        'active_thread': f'direct-{conversation.pk}',
        'contact_online': _is_online(contact),
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
        'ws_path': f'/ws/chat/direct/{conversation.pk}/',
        'message_kind': 'direct',
        'can_block': user.is_student() and contact.is_student(),
        'is_blocked': ChatBlock.objects.filter(blocker=user, blocked=contact).exists(),
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
    return conversation_messages_response(
        request, user, conversation,
        payload=_private_message_payload,
        kind=realtime.KIND_CONSULTATION,
        select=('sender', 'lesson', 'question__quiz'),
    )


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
    restriction = student_quiet_hours_restriction(user, conversation.classroom)
    if restriction:
        return JsonResponse({'error': restriction}, status=403)
    parsed = parse_send_request(request)
    if isinstance(parsed, JsonResponse):
        return parsed
    lesson, question, context_error = _resolve_message_context(user, conversation, parsed)
    if context_error:
        return JsonResponse({'error': context_error}, status=400)
    message = PrivateMessage(
        conversation=conversation,
        sender=user,
        body=parsed['body'],
        attachment_name=parsed['attachment_name'],
        is_voice=parsed['is_voice'],
        lesson=lesson,
        question=question,
    )
    if parsed['upload']:
        message.attachment = parsed['upload']
    message.save()
    conversation.save(update_fields=['updated_at'])
    realtime.conversation_changed(realtime.KIND_CONSULTATION, conversation.pk)
    from notifications.services import notify_new_private_message
    notify_new_private_message(
        realtime.KIND_CONSULTATION, conversation, message,
        conversation.teacher if user.pk == conversation.student_id else conversation.student,
    )
    return JsonResponse({'ok': True, 'message': _private_message_payload(message, user)})


def _resolve_message_context(user, conversation, parsed):
    """Valide la leçon ou la question jointe à un message de consultation."""
    from education.models import Lesson
    from quizzes.models import Attempt, Question

    lesson = question = None
    if parsed['question_id']:
        question = Question.objects.select_related('quiz').filter(pk=parsed['question_id']).first()
        if question is None:
            return None, None, 'Question introuvable.'
        quiz = question.quiz
        allowed = (
            quiz.created_by_id == conversation.teacher_id
            or Attempt.objects.filter(student=conversation.student, quiz=quiz).exists()
        )
        if not allowed:
            return None, None, 'Cette question ne concerne pas cette conversation.'
        lesson = quiz.lesson
    elif parsed['lesson_id']:
        lesson = Lesson.objects.filter(pk=parsed['lesson_id']).first()
        if lesson is None:
            return None, None, 'Leçon introuvable.'
    return lesson, question, ''


@login_required_simple
@require_GET
def private_attachment(request, message_id):
    user = get_edubac_user(request)
    message = get_object_or_404(
        PrivateMessage.objects.select_related('conversation'),
        pk=message_id,
        deleted_at__isnull=True,
        conversation__in=_private_conversations_for(user),
    )
    return serve_attachment(message.attachment, message.attachment_name)
