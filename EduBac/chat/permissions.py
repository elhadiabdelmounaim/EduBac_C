"""Contrôle d'accès Backend pour Prof-Étudiant Chat."""
from django.db.models import Q
from django.contrib.auth import get_user_model

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
    other = conversation.other_participant(user)
    if is_platform_admin(user):
        return bool(
            conversation.participant_one.is_student()
            != conversation.participant_two.is_student()
            and (
                is_platform_admin(conversation.participant_one)
                or is_platform_admin(conversation.participant_two)
            )
        )
    if other is None:
        return False
    if not user.is_student():
        return False
    if is_platform_admin(other):
        return True
    if not other.is_student() or not conversation.classroom_id:
        return False
    return ClassroomMember.objects.filter(
        user=user,
        classroom__is_active=True,
        classroom__members__user=other,
    ).exists()


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
        memberships = ClassroomMember.objects.filter(
            user=user,
            classroom__members__user=target,
            classroom__is_active=True,
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
