"""Contrôle d'accès Backend pour Prof-Étudiant Chat."""
from django.db.models import Q
from django.contrib.auth import get_user_model
from django.utils import timezone

from chat.models import DirectConversation
from classrooms.models import Classroom, ClassroomMember


def is_platform_admin(user):
    return bool(
        user
        and getattr(user, 'is_authenticated', False)
        and (
            getattr(user, 'is_staff', False)
            or getattr(user, 'is_superuser', False)
        )
    )


def platform_admin_user():
    """Return a stable platform inbox owner; all staff can answer that inbox."""
    user_model = get_user_model()
    return (
        user_model.objects.filter(is_active=True, is_superuser=True).order_by('pk').first()
        or user_model.objects.filter(is_active=True, is_staff=True).order_by('pk').first()
    )


def get_edubac_user(request):
    return getattr(request, 'edubac_user', None) or (
        request.user if getattr(request.user, 'is_authenticated', False) else None
    )


def user_can_access_classroom(user, classroom) -> bool:
    """
    Enseignant : uniquement ses classes (teacher FK).
    Élève : uniquement les classes dont il est membre.
    """
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    if is_platform_admin(user):
        return True
    if user.is_teacher():
        return classroom.teacher_id == user.id
    if user.is_student():
        return classroom.is_active and ClassroomMember.objects.filter(
            classroom=classroom,
            user=user,
        ).exists()
    return False


def classrooms_for_user(user):
    """Liste des classes accessibles pour le chat."""
    if not user or not getattr(user, 'is_authenticated', False):
        return Classroom.objects.none()
    if is_platform_admin(user):
        return Classroom.objects.all().order_by('name')
    if user.is_teacher():
        return Classroom.objects.filter(teacher=user, is_active=True).order_by('name')
    if user.is_student():
        ids = ClassroomMember.objects.filter(user=user).values_list('classroom_id', flat=True)
        return Classroom.objects.filter(pk__in=ids, is_active=True).order_by('name')
    return Classroom.objects.none()


def _peer_chat_classrooms(user_ref, other_ref):
    """Classes actives communes où le professeur autorise les messages entre élèves."""
    return Classroom.objects.filter(
        is_active=True,
        chat_room__allow_student_direct=True,
        members__user=user_ref,
    ).filter(members__user=other_ref)


def accessible_direct_conversations(user):
    """Conversations individuelles que l'utilisateur peut lire et alimenter.

    - Administration : conversations élève ↔ administration.
    - Élève : avec l'administration, ou avec un camarade d'une classe active
      commune dont le professeur a autorisé les messages entre élèves, et sans
      blocage entre eux.
    """
    from django.db.models import Exists, OuterRef

    if not user or not getattr(user, 'is_authenticated', False):
        return DirectConversation.objects.none()
    if is_platform_admin(user):
        return direct_conversations_for(user)
    if not user.is_student():
        return DirectConversation.objects.none()

    user_model = get_user_model()
    admin_ids = user_model.objects.filter(
        Q(is_staff=True) | Q(is_superuser=True),
    ).values('pk')
    mine = DirectConversation.objects.filter(
        Q(participant_one=user) | Q(participant_two=user),
    )
    with_admin = Q(participant_one_id__in=admin_ids) | Q(participant_two_id__in=admin_ids)
    peer_allowed = (
        (Q(participant_one=user) & Exists(_peer_chat_classrooms(user, OuterRef('participant_two'))))
        | (Q(participant_two=user) & Exists(_peer_chat_classrooms(user, OuterRef('participant_one'))))
    )
    # Un blocage n'empêche pas de relire l'historique (ni de débloquer) :
    # il interdit l'envoi, vérifié par api_direct_send et le démarrage.
    return mine.filter(with_admin | peer_allowed).select_related(
        'participant_one', 'participant_two', 'classroom',
    ).order_by('-updated_at')


def direct_conversations_for(user):
    if not user or not getattr(user, 'is_authenticated', False):
        return DirectConversation.objects.none()
    if is_platform_admin(user):
        user_model = get_user_model()
        admin_ids = user_model.objects.filter(
            Q(is_staff=True) | Q(is_superuser=True),
        ).values('pk')
        student_ids = user_model.objects.filter(
            role='student',
            is_staff=False,
            is_superuser=False,
        ).values('pk')
        conversations = DirectConversation.objects.filter(
            (
                Q(participant_one_id__in=admin_ids)
                & Q(participant_two_id__in=student_ids)
            )
            | (
                Q(participant_two_id__in=admin_ids)
                & Q(participant_one_id__in=student_ids)
            )
        )
    else:
        conversations = DirectConversation.objects.filter(
            Q(participant_one=user) | Q(participant_two=user),
        )
    return conversations.select_related(
        'participant_one', 'participant_two', 'classroom',
    ).order_by('-updated_at')

def user_can_access_direct_conversation(user, conversation):
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    if is_platform_admin(user):
        return bool(
            conversation.participant_one.is_student()
            != conversation.participant_two.is_student()
            and (
                is_platform_admin(conversation.participant_one)
                or is_platform_admin(conversation.participant_two)
            )
        )
    return accessible_direct_conversations(user).filter(pk=conversation.pk).exists()


def can_moderate_classroom(user, classroom):
    """Professeur de la classe ou administration."""
    return bool(
        user
        and getattr(user, 'is_authenticated', False)
        and (
            is_platform_admin(user)
            or (user.is_teacher() and classroom.teacher_id == user.pk)
        )
    )


def class_post_restriction(user, room):
    """Raison pour laquelle l'utilisateur ne peut pas écrire dans le salon, ou ''."""
    if can_moderate_classroom(user, room.classroom):
        return ''
    if room.is_locked:
        return 'Le professeur a réservé ce salon à ses messages.'
    mute = room.active_mute_for(user)
    if mute:
        local = timezone.localtime(mute.until)
        return f'Vous ne pouvez pas écrire dans ce salon avant le {local:%d/%m à %H:%M}.'
    if room.in_quiet_hours():
        return quiet_hours_message(room)
    return ''


def class_reaction_restriction(user, room):
    """Réagir à un message du salon : permis même en mode annonces, pas en sourdine
    ni pendant les heures de silence (professeur et administration : toujours)."""
    if can_moderate_classroom(user, room.classroom):
        return ''
    mute = room.active_mute_for(user)
    if mute:
        local = timezone.localtime(mute.until)
        return f'Vous ne pouvez pas réagir dans ce salon avant le {local:%d/%m à %H:%M}.'
    if room.in_quiet_hours():
        return quiet_hours_message(room)
    return ''


def quiet_hours_message(room):
    return (
        f'Heures de silence ({room.quiet_hours_start:%H:%M} – '
        f'{room.quiet_hours_end:%H:%M}) : les messages des élèves reprendront ensuite.'
    )


def student_quiet_hours_restriction(user, classroom):
    """Heures de silence de la classe appliquées aux messages privés d'un élève."""
    if not classroom or not user or not user.is_student():
        return ''
    from chat.models import ClassChatRoom
    room = ClassChatRoom.objects.filter(classroom=classroom).first()
    if room and room.in_quiet_hours():
        return quiet_hours_message(room)
    return ''


def direct_conversation_start_context(user, target, classroom_id=None):
    """Return allowed conversation mode and class, or None for forbidden targets."""
    if not user or not target or user.pk == target.pk:
        return None
    if user.is_student():
        if is_platform_admin(target):
            main_admin = platform_admin_user()
            if main_admin and target.pk != main_admin.pk:
                return None
            return {'kind': 'direct', 'classroom': None}
        if target.is_teacher():
            teacher_memberships = ClassroomMember.objects.filter(
                user=user,
                classroom__teacher=target,
                classroom__is_active=True,
            )
            if classroom_id:
                teacher_memberships = teacher_memberships.filter(
                    classroom_id=classroom_id,
                )
            teacher_membership = teacher_memberships.select_related('classroom').first()
            if teacher_membership:
                return {'kind': 'consultation', 'classroom': teacher_membership.classroom}
        if not target.is_student():
            return None
        from chat.models import ChatBlock
        if ChatBlock.between(user, target):
            return None
        memberships = ClassroomMember.objects.filter(
            user=user,
            classroom__members__user=target,
            classroom__is_active=True,
            classroom__chat_room__allow_student_direct=True,
        )
        if classroom_id:
            memberships = memberships.filter(classroom_id=classroom_id)
        membership = memberships.select_related('classroom').first()
        if not membership:
            return None
        return {'kind': 'direct', 'classroom': membership.classroom}
    if is_platform_admin(user) and target.is_student():
        return {'kind': 'direct', 'classroom': None}
    if user.is_teacher() and target.is_student():
        memberships = ClassroomMember.objects.filter(
            classroom__teacher=user,
            classroom__is_active=True,
            user=target,
        )
        if classroom_id:
            memberships = memberships.filter(classroom_id=classroom_id)
        membership = memberships.select_related('classroom').first()
        if membership:
            return {'kind': 'consultation', 'classroom': membership.classroom}
    return None
