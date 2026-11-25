"""Modération et outils de la messagerie : édition, suppression, signalement,
réglages du salon de classe, mise en sourdine, blocage et brouillon IA."""
import json
import logging
import time
from datetime import timedelta

from django.contrib import messages as flash
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_time
from django.views.decorators.http import require_GET, require_POST

from accounts.decorators import login_required_simple
from classrooms.models import Classroom, ClassroomMember

from . import realtime
from .models import (
    ChatBlock,
    ChatMessage,
    ChatMute,
    ChatReport,
    ClassChatRoom,
    DirectMessage,
    MessageReaction,
    PrivateConversation,
    PrivateMessage,
)
from .permissions import (
    can_moderate_classroom,
    class_reaction_restriction,
    student_quiet_hours_restriction,
    get_edubac_user,
    is_platform_admin,
    platform_admin_user,
    user_can_access_classroom,
    user_can_access_direct_conversation,
)

logger = logging.getLogger(__name__)

MUTE_DURATIONS = {0, 15, 60, 24 * 60, 7 * 24 * 60}
SNAPSHOT_CONTEXT = 5


def _json_body(request):
    try:
        data = json.loads(request.body.decode('utf-8') or '{}')
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


# ─── Résolution d'un message, quel que soit son type ─────────────────────────

class _Target:
    """Message résolu avec son contexte d'accès."""

    def __init__(self, message, classroom, *, moderator, notify):
        self.message = message
        self.classroom = classroom
        self.moderator = moderator
        self.notify = notify


def _resolve(user, kind, message_id):
    """Retourne le message si l'utilisateur peut le lire, sinon lève Http404."""
    from .views import _private_conversations_for

    if kind == ChatReport.KIND_CLASS:
        message = ChatMessage.objects.select_related(
            'room__classroom', 'sender',
        ).filter(pk=message_id).first()
        if not message or not user_can_access_classroom(user, message.room.classroom):
            raise Http404
        classroom = message.room.classroom
        return _Target(
            message, classroom,
            moderator=can_moderate_classroom(user, classroom),
            notify=lambda: realtime.class_update(classroom.pk, message),
        )
    if kind == ChatReport.KIND_CONSULTATION:
        message = PrivateMessage.objects.select_related(
            'conversation__classroom', 'sender',
        ).filter(
            pk=message_id, conversation__in=_private_conversations_for(user),
        ).first()
        if not message:
            raise Http404
        conversation = message.conversation
        return _Target(
            message, conversation.classroom,
            moderator=False,
            notify=lambda: realtime.conversation_changed(
                realtime.KIND_CONSULTATION, conversation.pk, event='update',
            ),
        )
    if kind == ChatReport.KIND_DIRECT:
        message = DirectMessage.objects.select_related(
            'conversation__participant_one', 'conversation__participant_two',
            'conversation__classroom', 'sender',
        ).filter(pk=message_id).first()
        if not message or not user_can_access_direct_conversation(user, message.conversation):
            raise Http404
        conversation = message.conversation
        return _Target(
            message, conversation.classroom,
            moderator=is_platform_admin(user),
            notify=lambda: realtime.conversation_changed(
                realtime.KIND_DIRECT, conversation.pk, event='update',
            ),
        )
    raise Http404


def _message_payload(kind, message, user):
    from .reactions import charger
    noms = kind == ChatReport.KIND_CLASS and can_moderate_classroom(user, message.room.classroom)
    charger(kind, [message], noms=noms)
    if kind == ChatReport.KIND_CLASS:
        return message.to_dict(user)
    from .payloads import conversation_message_payload
    route = 'chat:private_attachment' if kind == ChatReport.KIND_CONSULTATION else 'chat:direct_attachment'
    return conversation_message_payload(message, user, route)


@login_required_simple
@require_POST
def api_message_edit(request, kind, message_id):
    user = get_edubac_user(request)
    target = _resolve(user, kind, message_id)
    message = target.message
    data = _json_body(request)
    body = (data or {}).get('body')
    if not isinstance(body, str) or not body.strip():
        return JsonResponse({'error': 'Le message ne peut pas être vide.'}, status=400)
    body = body.strip()
    if len(body) > 4000:
        return JsonResponse({'error': 'Message trop long (4 000 caractères maximum).'}, status=400)
    if not message.can_edit(user):
        return JsonResponse(
            {'error': 'Ce message ne peut plus être modifié (5 minutes après l’envoi).'},
            status=403,
        )
    message.edit_body(body)
    target.notify()
    return JsonResponse({'ok': True, 'message': _message_payload(kind, message, user)})


@login_required_simple
@require_POST
def api_message_delete(request, kind, message_id):
    user = get_edubac_user(request)
    target = _resolve(user, kind, message_id)
    message = target.message
    if message.is_deleted:
        return JsonResponse({'ok': True, 'message': _message_payload(kind, message, user)})
    if message.sender_id != user.pk and not target.moderator:
        return JsonResponse({'error': 'Vous ne pouvez supprimer que vos messages.'}, status=403)
    message.soft_delete(user)
    if kind == ChatReport.KIND_CLASS and message.is_pinned:
        message.is_pinned = False
        message.touch('is_pinned')
    target.notify()
    return JsonResponse({'ok': True, 'message': _message_payload(kind, message, user)})


def _reaction_restriction(user, kind, target):
    message = target.message
    if kind == ChatReport.KIND_CLASS:
        return class_reaction_restriction(user, message.room)
    if kind == ChatReport.KIND_CONSULTATION:
        return student_quiet_hours_restriction(user, target.classroom)
    other = message.conversation.other_participant(user)
    if other and ChatBlock.between(user, other):
        return 'Les messages sont bloqués entre vous et ce camarade.'
    if other and other.is_student() and user.is_student():
        return student_quiet_hours_restriction(user, target.classroom)
    return ''


@login_required_simple
@require_POST
def api_message_react(request, kind, message_id):
    """Une réaction par personne et par message : la même la retire, une autre la remplace."""
    user = get_edubac_user(request)
    target = _resolve(user, kind, message_id)
    message = target.message
    emoji = (_json_body(request) or {}).get('emoji')
    if emoji not in MessageReaction.EMOJIS:
        return JsonResponse({'error': 'Réaction inconnue.'}, status=400)
    if message.is_deleted:
        return JsonResponse({'error': 'Ce message a été supprimé.'}, status=400)
    restriction = _reaction_restriction(user, kind, target)
    if restriction:
        return JsonResponse({'error': restriction}, status=403)
    with transaction.atomic():
        existante = MessageReaction.objects.filter(kind=kind, message_id=message.pk, user=user).first()
        if existante and existante.emoji == emoji:
            existante.delete()
        elif existante:
            existante.emoji = emoji
            existante.save(update_fields=['emoji'])
        else:
            MessageReaction.objects.create(kind=kind, message_id=message.pk, user=user, emoji=emoji)
        message.touch()          # les autres navigateurs reçoivent le changement à la synchronisation
    target.notify()
    return JsonResponse({'ok': True, 'message': _message_payload(kind, message, user)})


# ─── Signalements ─────────────────────────────────────────────────────────────

def _describe(message):
    if message.is_deleted:
        return '[message supprimé]'
    if message.body:
        return message.body[:1000]
    if message.is_voice:
        return '[message vocal]'
    return f'[pièce jointe : {message.attachment_name}]' if message.attachment_name else '[vide]'


def _snapshot(kind, message):
    if kind == ChatReport.KIND_CLASS:
        siblings = message.room.messages
    else:
        siblings = message.conversation.messages
    previous = list(
        siblings.filter(created_at__lte=message.created_at)
        .exclude(pk=message.pk)
        .select_related('sender')
        .order_by('-created_at')[:SNAPSHOT_CONTEXT]
    )
    items = list(reversed(previous)) + [message]
    return [
        {
            'sender': item.sender.get_full_name() or item.sender.username,
            'sender_id': item.sender_id,
            'body': _describe(item),
            'created_at': timezone.localtime(item.created_at).strftime('%d/%m/%Y %H:%M'),
            'reported': item.pk == message.pk,
        }
        for item in items
    ]


def _report_reviewers(report):
    """Professeur de la classe (sauf s'il est visé) et administration."""
    reviewers = []
    classroom = report.classroom
    if (
        report.kind != ChatReport.KIND_CONSULTATION
        and classroom
        and classroom.teacher_id
        and classroom.teacher_id != report.reported_user_id
    ):
        reviewers.append(classroom.teacher)
    admin = platform_admin_user()
    if admin and admin.pk not in {r.pk for r in reviewers} and admin.pk != report.reported_user_id:
        reviewers.append(admin)
    return reviewers


@login_required_simple
@require_POST
def api_message_report(request, kind, message_id):
    user = get_edubac_user(request)
    target = _resolve(user, kind, message_id)
    message = target.message
    if message.sender_id == user.pk:
        return JsonResponse({'error': 'Vous ne pouvez pas signaler votre propre message.'}, status=400)
    data = _json_body(request) or {}
    reason = data.get('reason')
    if reason not in dict(ChatReport.REASON_CHOICES):
        return JsonResponse({'error': 'Choisissez un motif de signalement.'}, status=400)
    details = str(data.get('details') or '').strip()[:1000]
    try:
        with transaction.atomic():
            report = ChatReport.objects.create(
                kind=kind,
                message_id=message.pk,
                classroom=target.classroom,
                reporter=user,
                reported_user=message.sender,
                reason=reason,
                details=details,
                snapshot=_snapshot(kind, message),
            )
    except IntegrityError:
        return JsonResponse({'ok': True, 'already_reported': True})
    from notifications.services import notify_report
    notify_report(report, _report_reviewers(report))
    return JsonResponse({'ok': True})


def _visible_reports(user):
    reports = ChatReport.objects.select_related(
        'classroom', 'reporter', 'reported_user', 'handled_by',
    )
    if is_platform_admin(user):
        return reports
    if user.is_teacher():
        return reports.filter(
            kind__in=[ChatReport.KIND_CLASS, ChatReport.KIND_DIRECT],
            classroom__teacher=user,
        ).exclude(reported_user=user)
    return reports.none()


@login_required_simple
@require_GET
def moderation_dashboard(request):
    user = get_edubac_user(request)
    if not (user.is_teacher() or is_platform_admin(user)):
        raise Http404
    status = request.GET.get('statut', ChatReport.STATUS_OPEN)
    if status not in dict(ChatReport.STATUS_CHOICES):
        status = ChatReport.STATUS_OPEN
    reports = _visible_reports(user)
    return render(request, 'chat/moderation.html', {
        'reports': reports.filter(status=status)[:200],
        'status': status,
        'status_choices': ChatReport.STATUS_CHOICES,
        'open_count': reports.filter(status=ChatReport.STATUS_OPEN).count(),
        'page_title': 'Modération de la messagerie',
    })


def _report_message(report):
    model = {
        ChatReport.KIND_CLASS: ChatMessage,
        ChatReport.KIND_CONSULTATION: PrivateMessage,
        ChatReport.KIND_DIRECT: DirectMessage,
    }[report.kind]
    return model.objects.filter(pk=report.message_id).first()


@login_required_simple
@require_POST
def moderation_action(request, report_id):
    user = get_edubac_user(request)
    report = get_object_or_404(_visible_reports(user), pk=report_id)
    action = request.POST.get('action')
    note = (request.POST.get('note') or '').strip()[:500]
    if action not in {'resolve', 'dismiss', 'delete', 'mute'}:
        flash.error(request, 'Action inconnue.')
        return redirect('chat:moderation')

    message = _report_message(report)
    if action == 'delete' and message and not message.is_deleted:
        message.soft_delete(user)
        if report.kind == ChatReport.KIND_CLASS:
            realtime.class_update(message.room.classroom_id, message)
        else:
            realtime.conversation_changed(report.kind, message.conversation_id, event='update')
        note = note or 'Message supprimé.'
    if action == 'mute':
        if not (report.classroom and report.reported_user and report.reported_user.is_student()):
            flash.error(request, 'La sourdine ne s’applique qu’aux élèves d’une classe.')
            return redirect('chat:moderation')
        room = ClassChatRoom.get_or_create_for(report.classroom)
        ChatMute.objects.update_or_create(
            room=room, user=report.reported_user,
            defaults={'until': timezone.now() + timedelta(days=1), 'created_by': user},
        )
        realtime.class_room_changed(report.classroom_id)
        note = note or 'Élève mis en sourdine 24 h dans le salon de classe.'

    report.status = 'dismissed' if action == 'dismiss' else 'resolved'
    report.handled_by = user
    report.handled_at = timezone.now()
    report.resolution_note = note
    report.save(update_fields=['status', 'handled_by', 'handled_at', 'resolution_note'])
    flash.success(request, 'Signalement traité.')
    return redirect('chat:moderation')


# ─── Réglages du salon de classe ──────────────────────────────────────────────

def _moderated_room(request, classroom_id):
    user = get_edubac_user(request)
    classroom = get_object_or_404(Classroom, pk=classroom_id)
    if not can_moderate_classroom(user, classroom):
        return user, None, JsonResponse({'error': 'Réservé au professeur de la classe.'}, status=403)
    return user, ClassChatRoom.get_or_create_for(classroom), None


def _parse_quiet_time(value):
    if value in (None, ''):
        return None
    parsed = parse_time(str(value))
    if parsed is None:
        raise ValueError
    return parsed.replace(second=0, microsecond=0)


@login_required_simple
@require_POST
def api_room_settings(request, classroom_id):
    user, room, err = _moderated_room(request, classroom_id)
    if err:
        return err
    data = _json_body(request)
    if data is None:
        return JsonResponse({'error': 'Requête invalide.'}, status=400)
    fields = []
    for key in ('is_locked', 'allow_student_direct'):
        if key in data:
            setattr(room, key, bool(data[key]))
            fields.append(key)
    if 'quiet_hours_start' in data or 'quiet_hours_end' in data:
        try:
            start = _parse_quiet_time(data.get('quiet_hours_start'))
            end = _parse_quiet_time(data.get('quiet_hours_end'))
        except ValueError:
            return JsonResponse({'error': 'Heure invalide (format HH:MM).'}, status=400)
        if bool(start) != bool(end):
            return JsonResponse(
                {'error': 'Indiquez le début et la fin des heures de silence, ou aucune des deux.'},
                status=400,
            )
        if start and start == end:
            return JsonResponse({'error': 'Le début et la fin doivent être différents.'}, status=400)
        room.quiet_hours_start, room.quiet_hours_end = start, end
        fields += ['quiet_hours_start', 'quiet_hours_end']
    if fields:
        room.save(update_fields=fields)
        realtime.class_room_changed(room.classroom_id)
    from .views import _room_state
    return JsonResponse({'ok': True, 'room': _room_state(room, user)})


@login_required_simple
@require_POST
def api_room_mute(request, classroom_id):
    user, room, err = _moderated_room(request, classroom_id)
    if err:
        return err
    data = _json_body(request) or {}
    try:
        target_id = int(data.get('user_id'))
        minutes = int(data.get('minutes'))
    except (TypeError, ValueError):
        return JsonResponse({'error': 'Requête invalide.'}, status=400)
    if minutes not in MUTE_DURATIONS:
        return JsonResponse({'error': 'Durée non prise en charge.'}, status=400)
    membership = ClassroomMember.objects.filter(
        classroom=room.classroom, user_id=target_id, user__role='student',
    ).select_related('user').first()
    if membership is None:
        return JsonResponse({'error': 'Cet élève ne fait pas partie de la classe.'}, status=404)
    if minutes == 0:
        ChatMute.objects.filter(room=room, user=membership.user).delete()
        until = None
    else:
        until = timezone.now() + timedelta(minutes=minutes)
        ChatMute.objects.update_or_create(
            room=room, user=membership.user,
            defaults={'until': until, 'created_by': user},
        )
    realtime.class_room_changed(room.classroom_id)
    return JsonResponse({
        'ok': True,
        'muted_until': timezone.localtime(until).strftime('%d/%m %H:%M') if until else '',
    })


# ─── Blocage entre élèves ─────────────────────────────────────────────────────

@login_required_simple
@require_POST
def api_block(request):
    user = get_edubac_user(request)
    if not user.is_student():
        return JsonResponse({'error': 'Réservé aux élèves.'}, status=403)
    data = _json_body(request) or {}
    try:
        target_id = int(data.get('user_id'))
    except (TypeError, ValueError):
        return JsonResponse({'error': 'Requête invalide.'}, status=400)
    target = get_user_model().objects.filter(pk=target_id).first()
    if not target or not target.is_student() or target.pk == user.pk:
        return JsonResponse({'error': 'Seul un camarade peut être bloqué.'}, status=400)
    if data.get('blocked', True):
        ChatBlock.objects.get_or_create(blocker=user, blocked=target)
        blocked = True
    else:
        ChatBlock.objects.filter(blocker=user, blocked=target).delete()
        blocked = False
    return JsonResponse({'ok': True, 'blocked': blocked})


# ─── Brouillon de réponse IA pour le professeur ───────────────────────────────

AI_DRAFT_PER_MINUTE = 6

AI_DRAFT_SYSTEM = (
    "Tu aides un professeur de mathématiques de lycée (Bac marocain) à répondre "
    "à un élève dans une messagerie privée. Rédige UNIQUEMENT le brouillon de "
    "réponse du professeur, en français, au tutoiement, bienveillant et concis "
    "(10 lignes maximum). Explique la méthode pas à pas plutôt que de donner "
    "seulement le résultat. Écris les formules en LaTeX entre $...$. "
    "N'invente pas de contenu absent du contexte. Le professeur relira avant d'envoyer."
)


def _ai_rate_limited(user_id):
    key = f'chat-ai-draft:{user_id}:{int(time.time() // 60)}'
    if cache.add(key, 1, timeout=65):
        return False
    try:
        return cache.incr(key) > AI_DRAFT_PER_MINUTE
    except ValueError:
        cache.add(key, 1, timeout=65)
        return False


def _draft_prompt(conversation):
    recent = list(
        conversation.messages.filter(deleted_at__isnull=True)
        .select_related('sender', 'lesson', 'question__quiz__lesson')
        .order_by('-created_at')[:10]
    )
    recent.reverse()
    lesson = question = None
    for message in reversed(recent):
        if message.question_id and question is None:
            question = message.question
        if message.lesson_id and lesson is None:
            lesson = message.lesson
    if question and lesson is None:
        lesson = question.quiz.lesson

    parts = [f'Niveau de la classe : {conversation.classroom.get_niveau_display()}.']
    if lesson is not None:
        text = lesson.get_full_pedagogical_text()[:4000]
        parts.append(f'## Leçon concernée : {lesson.title}\n{text}')
    if question is not None:
        choices = '; '.join(
            f"{c.text}{' (bonne réponse)' if c.is_correct else ''}"
            for c in question.choices.all()
        )
        parts.append(
            f'## Question de quiz concernée\n{question.text}\n'
            f'Choix : {choices or "réponse libre"}\n'
            f'Réponse attendue : {question.correct_answer}\n'
            f'Explication : {question.explanation}'
        )
    lines = []
    for message in recent:
        who = 'Professeur' if message.sender_id == conversation.teacher_id else 'Élève'
        content = message.body or ('[message vocal]' if message.is_voice else f'[fichier : {message.attachment_name}]')
        lines.append(f'{who} : {content[:1500]}')
    parts.append('## Conversation récente\n' + '\n'.join(lines))
    return '\n\n'.join(parts)


@login_required_simple
@require_POST
def api_ai_draft(request, conversation_id):
    from ai.providers import AIProviderError, get_provider

    user = get_edubac_user(request)
    conversation = get_object_or_404(
        PrivateConversation.objects.select_related('classroom'),
        pk=conversation_id,
        teacher=user,
        classroom__teacher=user,
    )
    if not conversation.messages.filter(deleted_at__isnull=True).exclude(sender=user).exists():
        return JsonResponse({'error': 'L’élève n’a encore posé aucune question.'}, status=400)
    if _ai_rate_limited(user.pk):
        return JsonResponse({'error': 'Trop de demandes. Réessayez dans une minute.'}, status=429)
    try:
        draft = get_provider().chat(
            [
                {'role': 'system', 'content': AI_DRAFT_SYSTEM},
                {'role': 'user', 'content': _draft_prompt(conversation)},
            ],
            temperature=0.4,
            max_tokens=900,
            json_mode=False,
            timeout=60,
        )
    except AIProviderError as exc:
        message = (
            "L'assistant IA n'est pas configuré. Contactez l'administrateur."
            if exc.code == 'missing_api_key'
            else "L'assistant IA est momentanément indisponible. Réessayez."
        )
        return JsonResponse({'error': message}, status=503)
    except Exception:
        logger.exception('chat ai draft failed conversation=%s', conversation.pk)
        return JsonResponse({'error': "Impossible de préparer un brouillon pour le moment."}, status=503)
    draft = (draft or '').strip()[:4000]
    if not draft:
        return JsonResponse({'error': "L'assistant n'a proposé aucun brouillon. Réessayez."}, status=503)
    return JsonResponse({'ok': True, 'draft': draft})
