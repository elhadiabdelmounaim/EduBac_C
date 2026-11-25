import json
from collections import defaultdict
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count, Max, Q
from django.http import Http404, JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from accounts.decorators import login_required_simple
from classrooms.models import Classroom, ClassroomMember

from . import realtime
from .attachments import serve_attachment
from .conversation_api import conversation_messages_response, parse_send_request, resolve_reply
from .models import (
    ChatBlock,
    ChatPresence,
    ClassChatRoom,
    DirectConversation,
    DirectMessage,
    PrivateConversation,
)
from .payloads import conversation_message_payload
from .permissions import (
    can_moderate_classroom,
    direct_conversation_start_context,
    direct_conversations_for,
    get_edubac_user,
    is_platform_admin,
    platform_admin_user,
    student_quiet_hours_restriction,
    user_can_access_classroom,
    user_can_access_direct_conversation,
)


def _is_online(user):
    return bool(user and ChatPresence.objects.filter(
        user=user,
        last_seen_at__gte=timezone.now() - timedelta(seconds=90),
    ).exists())


def _direct_message_payload(message, user=None):
    return conversation_message_payload(message, user, 'chat:direct_attachment')


def _accessible_conversation(user, conversation_id):
    conversation = direct_conversations_for(user).filter(pk=conversation_id).first()
    if not conversation or not user_can_access_direct_conversation(user, conversation):
        return None
    return conversation


@login_required_simple
@require_GET
def api_direct_messages(request, conversation_id):
    user = get_edubac_user(request)
    conversation = _accessible_conversation(user, conversation_id)
    if conversation is None:
        return JsonResponse({'error': 'Cette conversation n’est plus accessible.'}, status=404)
    return conversation_messages_response(
        request, user, conversation,
        payload=_direct_message_payload,
        kind=realtime.KIND_DIRECT,
    )


@login_required_simple
@require_POST
def api_direct_send(request, conversation_id):
    user = get_edubac_user(request)
    conversation = _accessible_conversation(user, conversation_id)
    if conversation is None:
        return JsonResponse({'error': 'Cette conversation n’est plus accessible.'}, status=404)
    other = conversation.other_participant(user)
    if other and ChatBlock.between(user, other):
        return JsonResponse(
            {'error': 'Les messages sont bloqués entre vous et ce camarade.'}, status=403,
        )
    if other and other.is_student() and user.is_student():
        restriction = student_quiet_hours_restriction(user, conversation.classroom)
        if restriction:
            return JsonResponse({'error': restriction}, status=403)
    parsed = parse_send_request(request)
    if isinstance(parsed, JsonResponse):
        return parsed
    message = DirectMessage(
        conversation=conversation,
        sender=user,
        body=parsed['body'],
        attachment_name=parsed['attachment_name'],
        is_voice=parsed['is_voice'],
        reply_to=resolve_reply(conversation, parsed['reply_to_id']),
    )
    if parsed['upload']:
        message.attachment = parsed['upload']
    message.save()
    conversation.save(update_fields=['updated_at'])
    realtime.conversation_changed(realtime.KIND_DIRECT, conversation.pk)
    if other:
        from notifications.services import notify_new_private_message
        notify_new_private_message(realtime.KIND_DIRECT, conversation, message, other)
    return JsonResponse({'ok': True, 'message': _direct_message_payload(message, user)})


@login_required_simple
@require_GET
def direct_attachment(request, message_id):
    user = get_edubac_user(request)
    message = DirectMessage.objects.select_related(
        'conversation__participant_one', 'conversation__participant_two',
        'conversation__classroom',
    ).filter(pk=message_id, deleted_at__isnull=True).first()
    if (
        not message
        or not user_can_access_direct_conversation(user, message.conversation)
    ):
        raise Http404
    return serve_attachment(message.attachment, message.attachment_name)


def _student_contact_queryset(user, query=''):
    users = get_user_model().objects.filter(
        is_active=True,
        role='student',
        is_staff=False,
        is_superuser=False,
        approval_status='approved',
    )
    if is_platform_admin(user):
        pass
    elif user.is_teacher():
        users = users.filter(
            classroom_memberships__classroom__teacher=user,
            classroom_memberships__classroom__is_active=True,
        )
    elif user.is_student():
        users = users.filter(
            classroom_memberships__classroom__members__user=user,
            classroom_memberships__classroom__is_active=True,
            classroom_memberships__classroom__chat_room__allow_student_direct=True,
        ).exclude(pk=user.pk).exclude(
            pk__in=ChatBlock.objects.filter(blocker=user).values('blocked'),
        ).exclude(
            pk__in=ChatBlock.objects.filter(blocked=user).values('blocker'),
        )
    else:
        users = users.none()
    if query:
        users = users.filter(
            Q(username__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(classroom_memberships__classroom__name__icontains=query)
        ).distinct()
    return users.distinct()


def _contact_payload(user, target, kind, classroom=None, online_ids=None):
    name = 'Admin EduBac' if is_platform_admin(target) else (
        target.get_full_name() or target.username
    )
    classroom_name = classroom.name if classroom else ''
    subtitle = (
        f'{classroom.name} · {classroom.get_niveau_display()}'
        if classroom else (
            'Administration de la plateforme'
            if is_platform_admin(target) else ''
        )
    )
    search_text = ' '.join(filter(None, (
        name, target.username, classroom_name, subtitle,
    ))).lower()
    return {
        'id': target.pk,
        'name': name,
        'subtitle': subtitle,
        'class_name': classroom_name,
        'classroom_id': classroom.pk if classroom else '',
        'kind': kind,
        'avatar_letter': (name[:1] or '?').upper(),
        'is_online': (
            target.pk in online_ids
            if online_ids is not None else _is_online(target)
        ),
        'search_text': search_text,
    }


@login_required_simple
@require_GET
def api_direct_contacts(request):
    user = get_edubac_user(request)
    query = (request.GET.get('q') or '').strip()[:100].lower()
    contacts = []
    online_ids = set(ChatPresence.objects.filter(
        last_seen_at__gte=timezone.now() - timedelta(seconds=90),
    ).values_list('user_id', flat=True))

    if user.is_student():
        memberships = list(
            ClassroomMember.objects.filter(
                user=user,
                classroom__is_active=True,
            ).select_related('classroom', 'classroom__teacher')
        )
        for membership in memberships:
            teacher = membership.classroom.teacher
            if teacher and not is_platform_admin(teacher):
                contacts.append(_contact_payload(
                    user, teacher, 'consultation', membership.classroom, online_ids,
                ))
        admin = platform_admin_user()
        if admin and admin.pk != user.pk and admin.pk not in {
            contact['id'] for contact in contacts
        }:
            contacts.append(_contact_payload(user, admin, 'direct', online_ids=online_ids))

    students = list(_student_contact_queryset(user, query).order_by(
        'last_name', 'first_name', 'username',
    )[:100])
    membership_map = defaultdict(list)
    if students:
        for membership in ClassroomMember.objects.filter(
            user_id__in=[student.pk for student in students],
            classroom__is_active=True,
        ).select_related('classroom').order_by('classroom__name'):
            membership_map[membership.user_id].append(membership)
    if user.is_student():
        shared_class_ids = set(ClassroomMember.objects.filter(
            user=user,
            classroom__is_active=True,
            classroom__chat_room__allow_student_direct=True,
        ).values_list('classroom_id', flat=True))
    else:
        shared_class_ids = set()

    for target in students:
        target_memberships = membership_map[target.pk]
        if user.is_teacher() and not is_platform_admin(user):
            teacher_memberships = [
                item for item in target_memberships
                if item.classroom.teacher_id == user.pk
            ]
            for membership in teacher_memberships:
                contacts.append(_contact_payload(
                    user,
                    target,
                    'consultation',
                    membership.classroom,
                    online_ids,
                ))
            continue

        candidate_memberships = (
            [
                item for item in target_memberships
                if item.classroom_id in shared_class_ids
            ]
            if user.is_student() else target_memberships
        )
        if query:
            matching_classrooms = [
                item for item in candidate_memberships
                if query in (
                    f'{item.classroom.name} {item.classroom.get_niveau_display()}'
                ).lower()
            ]
            if matching_classrooms:
                candidate_memberships = matching_classrooms
        membership = candidate_memberships[0] if candidate_memberships else None
        classroom = membership.classroom if membership else None
        contacts.append(_contact_payload(
            user, target, 'direct', classroom, online_ids,
        ))

    seen = set()
    results = []
    for contact in contacts:
        key = (
            contact['id'],
            contact['kind'],
            contact['classroom_id'] if contact['kind'] == 'consultation' else '',
        )
        if key in seen:
            continue
        seen.add(key)
        if query and query not in contact['search_text']:
            continue
        contact.pop('search_text', None)
        results.append(contact)
        if len(results) >= 40:
            break
    return JsonResponse({'contacts': results})


@login_required_simple
@require_POST
def api_direct_start(request):
    user = get_edubac_user(request)
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
        if not isinstance(payload, dict):
            raise ValueError('Contact invalide.')
        target_id = int(payload.get('user_id'))
        raw_classroom_id = payload.get('classroom_id')
        classroom_id = int(raw_classroom_id) if raw_classroom_id else None
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError):
        return JsonResponse({'error': 'Contact invalide.'}, status=400)
    target = get_user_model().objects.filter(pk=target_id, is_active=True).first()
    context = direct_conversation_start_context(user, target, classroom_id)
    if not context:
        return JsonResponse(
            {'error': 'Vous ne pouvez pas démarrer cette conversation.'},
            status=403,
        )
    if context['kind'] == 'consultation':
        conversation, _ = PrivateConversation.objects.get_or_create(
            classroom=context['classroom'],
            student=target if user.is_teacher() else user,
            teacher=user if user.is_teacher() else target,
        )
        url = reverse('chat:private_room', args=[conversation.pk])
        return JsonResponse({'ok': True, 'kind': 'consultation', 'url': url})

    conversation, _ = DirectConversation.get_or_create_for(
        user,
        target,
        classroom=context['classroom'],
    )
    return JsonResponse({
        'ok': True,
        'kind': 'direct',
        'url': reverse('chat:direct_room', args=[conversation.pk]),
    })


@login_required_simple
@require_POST
def api_presence(request):
    user = get_edubac_user(request)
    ChatPresence.objects.update_or_create(
        user=user,
        defaults={'last_seen_at': timezone.now()},
    )
    return JsonResponse({'ok': True})


@login_required_simple
@require_GET
def api_room_members(request, classroom_id):
    user = get_edubac_user(request)
    classroom = Classroom.objects.filter(pk=classroom_id).first()
    if not classroom or not user_can_access_classroom(user, classroom):
        return JsonResponse({'error': 'Accès refusé à cette classe.'}, status=404)
    room, _ = ClassChatRoom.objects.get_or_create(classroom=classroom)
    online_ids = set(ChatPresence.objects.filter(
        last_seen_at__gte=timezone.now() - timedelta(seconds=90),
    ).values_list('user_id', flat=True))
    stats = {
        row['sender_id']: row
        for row in room.messages.values('sender_id').annotate(
            message_count=Count('id'),
            last_message_at=Max('created_at'),
        )
    }
    members = []
    if classroom.teacher_id:
        teacher = classroom.teacher
        teacher_stats = stats.get(teacher.pk, {})
        members.append({
            'id': teacher.pk,
            'name': teacher.get_full_name() or teacher.username,
            'role': 'Enseignant',
            'message_count': teacher_stats.get('message_count', 0),
            'last_message_at': (
                timezone.localtime(teacher_stats['last_message_at']).strftime('%d/%m/%Y %H:%M')
                if teacher_stats.get('last_message_at') else ''
            ),
            'is_online': teacher.pk in online_ids,
        })
    moderator = can_moderate_classroom(user, classroom)
    mutes = {
        mute.user_id: mute.until
        for mute in room.mutes.filter(until__gt=timezone.now())
    } if moderator else {}
    for membership in classroom.members.select_related('user').order_by(
        'user__last_name', 'user__first_name', 'user__username',
    )[:300]:
        member = membership.user
        member_stats = stats.get(member.pk, {})
        members.append({
            'id': member.pk,
            'name': member.get_full_name() or member.username,
            'role': 'Élève',
            'muted_until': (
                timezone.localtime(mutes[member.pk]).strftime('%d/%m %H:%M')
                if member.pk in mutes else ''
            ),
            'message_count': member_stats.get('message_count', 0),
            'last_message_at': (
                timezone.localtime(member_stats['last_message_at']).strftime('%d/%m/%Y %H:%M')
                if member_stats.get('last_message_at') else ''
            ),
            'is_online': member.pk in online_ids,
        })
    online_count = classroom.members.filter(user_id__in=online_ids).count()
    if classroom.teacher_id in online_ids:
        online_count += 1
    return JsonResponse({
        'members': members,
        'classroom': classroom.name,
        'online_count': online_count,
        'can_moderate': moderator,
    })
