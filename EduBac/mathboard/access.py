"""Droits sur un document, calculés à partir des rôles et classes existants.

Niveaux : None < 'view' < 'edit' < 'manage'.

- manage : propriétaire, administrateur, enseignant de la classe partagée,
           membre de rôle « gestion ».
- edit   : membre « modification » ; élève de la classe si students_can_edit.
- view   : membre « lecture » ; élève de la classe partagée.
"""
from django.db.models import Q

from classrooms.models import ClassroomMember

from .models import WhiteboardDocument, WhiteboardMember

LEVELS = {None: 0, 'view': 1, 'edit': 2, 'manage': 3}
ROLE_LEVEL = {
    WhiteboardMember.ROLE_VIEWER: 'view',
    WhiteboardMember.ROLE_EDITOR: 'edit',
    WhiteboardMember.ROLE_MANAGER: 'manage',
}


def _is_admin(user):
    return bool(user and (user.is_staff or user.is_superuser))


def access_level(user, document):
    if not user or not getattr(user, 'is_authenticated', False) or not user.is_active:
        return None
    if _is_admin(user) or document.owner_id == user.pk:
        return 'manage'
    classroom = document.classroom
    if classroom and user.is_teacher() and classroom.teacher_id == user.pk:
        return 'manage'
    best = None
    member = WhiteboardMember.objects.filter(document=document, user=user).only('role').first()
    if member:
        best = ROLE_LEVEL[member.role]
    if classroom and user.is_student() and ClassroomMember.objects.filter(
            classroom=classroom, user=user).exists():
        class_level = 'edit' if document.students_can_edit else 'view'
        if LEVELS[class_level] > LEVELS[best]:
            best = class_level
    return best


def can(user, document, needed):
    return LEVELS[access_level(user, document)] >= LEVELS[needed]


def visible_documents(user):
    """Documents que l'utilisateur peut au moins consulter."""
    qs = WhiteboardDocument.objects.select_related('owner', 'classroom')
    if _is_admin(user):
        return qs
    student_classes = ClassroomMember.objects.filter(user=user).values('classroom_id')
    return qs.filter(
        Q(owner=user)
        | Q(members__user=user)
        | Q(classroom__teacher=user)
        | Q(classroom_id__in=student_classes)
    ).distinct()


def can_share_with_classroom(user, classroom):
    return _is_admin(user) or (user.is_teacher() and classroom.teacher_id == user.pk)


def can_invite(manager, target):
    """Qui peut être ajouté comme membre par ce gestionnaire.

    Enseignant : ses élèves et les autres enseignants. Élève : ses camarades de
    classe. Administrateur : tout compte actif.
    """
    if not target.is_active or target.pk == manager.pk:
        return False
    if _is_admin(manager):
        return True
    if manager.is_teacher():
        if target.is_teacher():
            return True
        return ClassroomMember.objects.filter(user=target, classroom__teacher=manager).exists()
    shared = ClassroomMember.objects.filter(user=manager).values('classroom_id')
    return target.is_student() and ClassroomMember.objects.filter(
        user=target, classroom_id__in=shared).exists()
