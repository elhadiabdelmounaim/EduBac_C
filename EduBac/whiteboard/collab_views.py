"""API de collaboration du tableau : synchronisation, présence, permissions, partage."""
import json
import logging
from datetime import timedelta

from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from accounts.decorators import login_required_simple
from accounts.models import User
from classrooms.models import Classroom, ClassroomMember

from . import realtime
from .collab import BACKGROUNDS, MAX_ZONES, OpError, apply_ops, ops_since
from .models import WhiteboardBoard, WhiteboardPresence
from .permissions import board_capabilities, is_board_manager, zone_of

logger = logging.getLogger(__name__)

ONLINE_SECONDS = 20
CURSOR_SECONDS = 8


def _user(request):
    return getattr(request, 'edubac_user', None) or request.user


def _json(request):
    try:
        data = json.loads(request.body.decode('utf-8') or '{}')
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _board(pk):
    return get_object_or_404(
        WhiteboardBoard.objects.select_related('classroom', 'created_by').defer('content'),
        pk=pk, is_active=True,
    )


def _name(user):
    return user.get_full_name() or user.username


def eligible_students(board):
    """Élèves pouvant être invités ou ayant accès au tableau."""
    ids = set(board.participants.values_list('pk', flat=True))
    if board.classroom_id:
        ids |= set(ClassroomMember.objects.filter(classroom_id=board.classroom_id).values_list('user_id', flat=True))
    return User.objects.filter(pk__in=ids, is_active=True).order_by('first_name', 'last_name', 'username')


def _audience(board):
    """Élèves qui voient effectivement le tableau."""
    if board.classroom_id and board.access_mode == WhiteboardBoard.ACCESS_CLASS:
        return eligible_students(board)
    return board.participants.filter(is_active=True)


def _managers(board):
    ids = {board.created_by_id}
    if board.classroom_id and board.classroom.teacher_id:
        ids.add(board.classroom.teacher_id)
    return User.objects.filter(pk__in=ids, is_active=True)


def board_state(board, user, caps):
    """Réglages et participants envoyés à chaque synchronisation."""
    now = timezone.now()
    presences = {p.user_id: p for p in WhiteboardPresence.objects.filter(board=board)}
    editors = set(board.editors.values_list('pk', flat=True))
    people = list(_managers(board)) + list(_audience(board))
    seen, participants = set(), []
    for person in people:
        if person.pk in seen:
            continue
        seen.add(person.pk)
        presence = presences.get(person.pk)
        online = bool(presence and presence.last_seen >= now - timedelta(seconds=ONLINE_SECONDS))
        cursor = None
        if (presence and person.pk != user.pk and presence.cursor_x is not None
                and presence.last_seen >= now - timedelta(seconds=CURSOR_SECONDS)):
            cursor = {'x': presence.cursor_x, 'y': presence.cursor_y}
        participants.append({
            'id': person.pk,
            'name': _name(person),
            'teacher': not person.is_student(),
            'online': online,
            'cursor': cursor,
            'hand': bool(presence and presence.hand_raised_at),
            'contributions': presence.contributions if presence else 0,
            'granted': person.pk in editors,
            'controller': board.controller_id == person.pk,
            'zone': zone_of(board, person.pk),
            'me': person.pk == user.pk,
        })
    return {
        'title': board.title,
        'caps': caps,
        'settings': {
            'students_can_edit': board.students_can_edit,
            'allow_draw': board.allow_draw,
            'allow_text': board.allow_text,
            'allow_delete': board.allow_delete,
            'allow_images': board.allow_images,
            'is_locked': board.is_locked,
            'access_mode': board.access_mode,
            'classroom': board.classroom.name if board.classroom_id else '',
            'controller': board.controller_id,
        },
        'zones': [
            {'label': zone.get('label') or f'Espace {i + 1}', 'members': zone.get('members') or []}
            for i, zone in enumerate(board.zones or [])
        ],
        'participants': participants,
    }


def _touch_presence(board, user, cursor):
    presence, _ = WhiteboardPresence.objects.get_or_create(board=board, user=user)
    fields = {'last_seen': timezone.now()}
    if isinstance(cursor, dict):
        x, y = cursor.get('x'), cursor.get('y')
        if isinstance(x, (int, float)) and isinstance(y, (int, float)) and abs(x) < 1e6 and abs(y) < 1e6:
            fields.update(cursor_x=float(x), cursor_y=float(y))
    elif cursor is False:
        fields.update(cursor_x=None, cursor_y=None)
    WhiteboardPresence.objects.filter(pk=presence.pk).update(**fields)


@login_required_simple
@require_POST
def sync(request, pk):
    """Envoie les modifications locales et reçoit celles des autres participants."""
    board = _board(pk)
    user = _user(request)
    caps = board_capabilities(user, board)
    if not caps['view']:
        return JsonResponse({'error': 'Accès refusé.'}, status=403)
    data = _json(request)
    if data is None:
        return JsonResponse({'error': 'Requête invalide.'}, status=400)
    client = str(data.get('client') or '')[:64]
    rejected, applied = [], []
    ops = data.get('ops') or []
    if ops:
        try:
            _, applied, rejected = apply_ops(board.pk, user, caps, ops, client)
        except OpError as exc:
            return JsonResponse({'error': str(exc)}, status=400)
        board.refresh_from_db(fields=['revision'])
        if applied:
            realtime.board_ops(board.pk, board.revision, applied)
    _touch_presence(board, user, data.get('cursor'))
    try:
        since = int(data.get('since', -1))
    except (TypeError, ValueError):
        since = -1
    changes = ops_since(board, since)
    response = {
        'revision': board.revision,
        'ops': changes or [],
        'rejected': rejected,
        'state': board_state(board, user, caps),
    }
    if changes is None:
        from .collab import ensure_ids
        ensure_ids(board.pk)
        content = WhiteboardBoard.objects.filter(pk=board.pk).values_list('content', flat=True).first() or {}
        response['reset'] = True
        response['content'] = {
            'version': 1,
            'background': content.get('background') if content.get('background') in BACKGROUNDS else 'grid',
            'objects': content.get('objects') or [],
        }
    return JsonResponse(response)


def _manager_board(request, pk):
    board = _board(pk)
    user = _user(request)
    if not is_board_manager(user, board):
        return board, user, JsonResponse({'error': 'Réservé à l’enseignant du tableau.'}, status=403)
    return board, user, None


def _student(board, user_id):
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return None
    return eligible_students(board).filter(pk=user_id).first()


def _changed(board, user):
    realtime.board_state(board.pk)
    return JsonResponse({'ok': True, 'state': board_state(board, user, board_capabilities(user, board))})


@login_required_simple
@require_POST
def update_settings(request, pk):
    """Permissions globales des élèves et verrouillage."""
    board, user, error = _manager_board(request, pk)
    if error:
        return error
    data = _json(request) or {}
    fields = []
    for name in ('students_can_edit', 'allow_draw', 'allow_text', 'allow_delete', 'allow_images', 'is_locked'):
        if name in data:
            setattr(board, name, bool(data[name]))
            fields.append(name)
    if fields:
        board.save(update_fields=fields)
    return _changed(board, user)


@login_required_simple
@require_POST
def give_control(request, pk):
    """Donne temporairement la main à un élève, ou la reprend (user_id vide)."""
    board, user, error = _manager_board(request, pk)
    if error:
        return error
    data = _json(request) or {}
    student = _student(board, data.get('user_id')) if data.get('user_id') else None
    if data.get('user_id') and student is None:
        return JsonResponse({'error': 'Élève introuvable pour ce tableau.'}, status=400)
    board.controller = student
    board.save(update_fields=['controller'])
    if student:
        WhiteboardPresence.objects.filter(board=board, user=student).update(hand_raised_at=None)
        _notify('notify_whiteboard_turn', board, student, user, 'control')
    return _changed(board, user)


@login_required_simple
@require_POST
def grant(request, pk):
    """Autorise (ou non) un élève précis à écrire, même si la classe ne peut pas."""
    board, user, error = _manager_board(request, pk)
    if error:
        return error
    data = _json(request) or {}
    student = _student(board, data.get('user_id'))
    if student is None:
        return JsonResponse({'error': 'Élève introuvable pour ce tableau.'}, status=400)
    if data.get('allowed'):
        board.editors.add(student)
        _notify('notify_whiteboard_turn', board, student, user, 'granted')
    else:
        board.editors.remove(student)
        if board.controller_id == student.pk:
            board.controller = None
            board.save(update_fields=['controller'])
    WhiteboardPresence.objects.filter(board=board, user=student).update(hand_raised_at=None)
    return _changed(board, user)


@login_required_simple
@require_POST
def raise_hand(request, pk):
    """L'élève demande l'autorisation d'écrire ou de dessiner."""
    board = _board(pk)
    user = _user(request)
    if not board_capabilities(user, board)['view'] or not user.is_student():
        return JsonResponse({'error': 'Accès refusé.'}, status=403)
    raised = bool((_json(request) or {}).get('raised'))
    presence, _ = WhiteboardPresence.objects.get_or_create(board=board, user=user)
    presence.hand_raised_at = timezone.now() if raised else None
    presence.last_seen = timezone.now()
    presence.save(update_fields=['hand_raised_at', 'last_seen'])
    if raised:
        _notify('notify_whiteboard_hand', board, user, list(_managers(board)))
    return _changed(board, user)


@login_required_simple
@require_POST
def update_zones(request, pk):
    """Divise le tableau en espaces de travail (colonnes) attribués à des groupes d'élèves."""
    board, user, error = _manager_board(request, pk)
    if error:
        return error
    data = _json(request) or {}
    zones = data.get('zones') or []
    if not isinstance(zones, list) or len(zones) > MAX_ZONES or len(zones) == 1:
        return JsonResponse({'error': f'Choisissez 2 à {MAX_ZONES} espaces, ou aucun.'}, status=400)
    allowed = set(eligible_students(board).values_list('pk', flat=True))
    cleaned, used = [], set()
    for index, zone in enumerate(zones):
        if not isinstance(zone, dict):
            return JsonResponse({'error': 'Espace invalide.'}, status=400)
        members = []
        for raw in zone.get('members') or []:
            if isinstance(raw, int) and raw in allowed and raw not in used:
                members.append(raw)
                used.add(raw)
        label = str(zone.get('label') or f'Groupe {index + 1}').strip()[:40] or f'Groupe {index + 1}'
        cleaned.append({'label': label, 'members': members})
    board.zones = cleaned
    board.save(update_fields=['zones'])
    return _changed(board, user)


def _teacher_classrooms(user):
    classrooms = Classroom.objects.filter(is_active=True)
    if not (user.is_staff or user.is_superuser):
        classrooms = classrooms.filter(teacher=user)
    return classrooms


@login_required_simple
@require_POST
def share_live(request, pk):
    """Ouvre le tableau vivant à toute une classe ou à des élèves choisis."""
    board, user, error = _manager_board(request, pk)
    if error:
        return error
    data = _json(request) or {}
    classroom_id = data.get('classroom_id')
    if classroom_id:
        classroom = _teacher_classrooms(user).filter(pk=classroom_id).first()
        if classroom is None:
            return JsonResponse({'error': 'Vous ne pouvez partager qu’avec une de vos classes.'}, status=403)
        board.classroom = classroom
    mode = data.get('mode') or board.access_mode
    if mode not in (WhiteboardBoard.ACCESS_CLASS, WhiteboardBoard.ACCESS_SELECTED):
        return JsonResponse({'error': 'Mode de partage inconnu.'}, status=400)
    if mode == WhiteboardBoard.ACCESS_CLASS and not board.classroom_id:
        return JsonResponse({'error': 'Choisissez une classe.'}, status=400)
    board.access_mode = mode
    board.save(update_fields=['classroom', 'access_mode'])
    if mode == WhiteboardBoard.ACCESS_SELECTED:
        ids = [i for i in data.get('student_ids') or [] if isinstance(i, int)]
        students = _shareable_students(user, board).filter(pk__in=ids)
        if not students.exists():
            return JsonResponse({'error': 'Choisissez au moins un élève.'}, status=400)
        board.participants.set(students)
    after = list(_audience(board))
    if data.get('notify', True):
        # « Partager et prévenir » : tous les élèves invités sont prévenus.
        _notify('notify_whiteboard_live_share', board, after, user)
    if data.get('post_to_chat') and board.classroom_id and mode == WhiteboardBoard.ACCESS_CLASS:
        post_board_link('class', board.classroom, user, board)
    return _changed(board, user)


def _shareable_students(user, board):
    """Élèves que l'enseignant peut inviter : ceux de ses classes (et déjà invités)."""
    class_ids = _teacher_classrooms(user).values_list('pk', flat=True)
    member_ids = ClassroomMember.objects.filter(classroom_id__in=class_ids).values_list('user_id', flat=True)
    return User.objects.filter(
        Q(pk__in=member_ids) | Q(pk__in=board.participants.values_list('pk', flat=True)),
        is_active=True,
    ).distinct()


@login_required_simple
@require_GET
def share_options(request, pk):
    """Classes et élèves proposés dans la fenêtre de partage."""
    board, user, error = _manager_board(request, pk)
    if error:
        return error
    selected = set(board.participants.values_list('pk', flat=True))
    classes = []
    for classroom in _teacher_classrooms(user).order_by('name'):
        members = ClassroomMember.objects.filter(classroom=classroom).select_related('user').order_by(
            'user__first_name', 'user__last_name')
        classes.append({
            'id': classroom.pk, 'name': classroom.name,
            'students': [
                {'id': m.user_id, 'name': _name(m.user), 'selected': m.user_id in selected}
                for m in members if m.user.is_active
            ],
        })
    return JsonResponse({
        'classroom_id': board.classroom_id, 'mode': board.access_mode, 'classes': classes,
    })


# --- Partage depuis une conversation ---------------------------------------

def post_board_link(kind, target, sender, board):
    """Publie le lien du tableau dans une conversation (sans bloquer le partage)."""
    from chat import realtime as chat_realtime
    from chat.models import ChatMessage, ClassChatRoom, DirectMessage, PrivateMessage

    url = reverse('whiteboard:room', args=[board.pk])
    body = f'🧑‍🏫 Tableau en direct : {board.title}\n{url}'
    try:
        if kind == 'class':
            room = ClassChatRoom.get_or_create_for(target)
            message = ChatMessage.objects.create(room=room, sender=sender, body=body)
            chat_realtime.class_message(target.pk, message)
        elif kind == 'consultation':
            message = PrivateMessage.objects.create(conversation=target, sender=sender, body=body)
            target.save(update_fields=['updated_at'])
            chat_realtime.conversation_changed(chat_realtime.KIND_CONSULTATION, target.pk)
        elif kind == 'direct':
            message = DirectMessage.objects.create(conversation=target, sender=sender, body=body)
            target.save(update_fields=['updated_at'])
            chat_realtime.conversation_changed(chat_realtime.KIND_DIRECT, target.pk)
        else:
            return None
        return message
    except Exception:
        logger.warning('whiteboard link post failed kind=%s', kind, exc_info=True)
        return None


def _notify_board_message(kind, target, message, sender, skip_ids):
    """Le lien posté dans la conversation prévient (téléphone compris) ceux qui
    n'ont pas déjà reçu « Tableau partagé avec vous » pour ce partage."""
    if message is None:
        return
    try:
        if kind == 'class':
            from chat.views import _push_class_message
            _push_class_message(target, message, sender, exclude_ids=skip_ids)
        else:
            from notifications.services import notify_new_private_message
            recipient = target.student if kind == 'consultation' else target.other_participant(sender)
            if recipient and recipient.pk not in skip_ids and recipient.pk != sender.pk:
                notify_new_private_message(kind, target, message, recipient)
    except Exception:
        logger.warning('whiteboard link notification failed kind=%s', kind, exc_info=True)


def _conversation_target(user, kind, conversation_id):
    """(cible, classe, élèves) d'une conversation à laquelle l'enseignant a accès."""
    from chat.models import PrivateConversation
    from chat.permissions import direct_conversations_for, user_can_access_classroom
    from chat.views import _private_conversations_for

    if kind == 'class':
        classroom = _teacher_classrooms(user).filter(pk=conversation_id).first()
        if classroom and user_can_access_classroom(user, classroom):
            return classroom, classroom, None
    elif kind == 'consultation':
        conversation = _private_conversations_for(user).filter(pk=conversation_id).first()
        if isinstance(conversation, PrivateConversation):
            return conversation, conversation.classroom, [conversation.student]
    elif kind == 'direct':
        conversation = direct_conversations_for(user).filter(pk=conversation_id).first()
        if conversation:
            other = conversation.other_participant(user)
            if other and other.is_student():
                return conversation, conversation.classroom, [other]
    return None, None, None


@login_required_simple
@require_GET
def my_boards(request):
    """Tableaux de l'enseignant, pour les partager depuis une conversation."""
    user = _user(request)
    if user.is_student():
        return JsonResponse({'error': 'Réservé aux enseignants.'}, status=403)
    boards = WhiteboardBoard.objects.filter(is_active=True).select_related('classroom').defer('content')
    if not (user.is_staff or user.is_superuser):
        boards = boards.filter(created_by=user)
    return JsonResponse({'boards': [
        {'id': b.pk, 'title': b.title, 'classroom': b.classroom.name if b.classroom_id else '',
         'updated': timezone.localtime(b.updated_at).strftime('%d/%m %H:%M')}
        for b in boards.order_by('-updated_at')[:30]
    ]})


@login_required_simple
@require_POST
def share_to_conversation(request):
    """Partage un tableau (existant ou nouveau) avec les membres d'une conversation."""
    user = _user(request)
    if user.is_student():
        return JsonResponse({'error': 'Réservé aux enseignants.'}, status=403)
    data = _json(request) or {}
    kind = data.get('kind')
    try:
        conversation_id = int(data.get('conversation_id'))
    except (TypeError, ValueError):
        return JsonResponse({'error': 'Conversation invalide.'}, status=400)
    target, classroom, students = _conversation_target(user, kind, conversation_id)
    if target is None:
        return JsonResponse({'error': 'Conversation introuvable.'}, status=404)
    if data.get('board_id'):
        board = get_object_or_404(WhiteboardBoard, pk=data.get('board_id'), is_active=True)
        if not is_board_manager(user, board):
            return JsonResponse({'error': 'Ce tableau ne vous appartient pas.'}, status=403)
    else:
        title = str(data.get('title') or '').strip()[:200] or 'Tableau de la conversation'
        board = WhiteboardBoard.objects.create(
            title=title, created_by=user, content={'version': 1, 'objects': []},
            classroom=classroom if kind == 'class' else None,
        )
    before = set(_audience(board).values_list('pk', flat=True))
    if kind == 'class':
        board.classroom = classroom
        board.access_mode = WhiteboardBoard.ACCESS_CLASS
        board.save(update_fields=['classroom', 'access_mode'])
    else:
        if not board.classroom_id or board.access_mode == WhiteboardBoard.ACCESS_SELECTED:
            board.access_mode = WhiteboardBoard.ACCESS_SELECTED
            board.save(update_fields=['access_mode'])
        board.participants.add(*students)
    newcomers = [s for s in _audience(board) if s.pk not in before]
    _notify('notify_whiteboard_live_share', board, newcomers, user)
    message = post_board_link(kind, target, user, board)
    _notify_board_message(kind, target, message, user, {s.pk for s in newcomers})
    realtime.board_state(board.pk)
    return JsonResponse({'ok': True, 'url': reverse('whiteboard:room', args=[board.pk]), 'id': board.pk})


def _notify(name, *args):
    try:
        from notifications import services
        getattr(services, name)(*args)
    except Exception:
        logger.warning('whiteboard notification failed: %s', name, exc_info=True)
