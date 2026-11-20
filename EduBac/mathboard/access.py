"""Droits sur un document, calculés à partir des rôles et classes existants.

Niveaux : None < 'view' < 'edit' < 'manage'.

- manage : propriétaire, administrateur, enseignant de la classe partagée,
           membre de rôle « gestion ».
- edit   : membre « modification » ; élève de la classe si students_can_edit.
- view   : membre « lecture » ; élève de la classe partagée.
  (Document « préparé » — class_visible faux : les élèves de la classe n'ont
  encore aucun accès ; l'enseignant de la classe, si.)

Copie d'élève (travail à rendre, `source` renseigné) :
- l'élève : gestion tant que la copie est « en cours », lecture une fois rendue ;
- le professeur du sujet (propriétaire ou enseignant de sa classe) : gestion
  dès que la copie est rendue (correction), rien avant ;
- aucun autre accès (pas de classe ni de membres sur une copie).
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
    if _is_admin(user):
        return 'manage'
    if document.submission_status:
        return _copy_level(user, document)
    if document.owner_id == user.pk:
        return 'manage'
    classroom = document.classroom
    if classroom and user.is_teacher() and classroom.teacher_id == user.pk:
        return 'manage'
    best = None
    member = WhiteboardMember.objects.filter(document=document, user=user).only('role').first()
    if member:
        best = ROLE_LEVEL[member.role]
    if classroom and document.class_visible and user.is_student() and ClassroomMember.objects.filter(
            classroom=classroom, user=user).exists():
        class_level = 'edit' if document.students_can_edit else 'view'
        if LEVELS[class_level] > LEVELS[best]:
            best = class_level
    return best


def is_corrector(user, subject):
    """Professeur qui corrige les copies de ce sujet."""
    if subject is None:
        return False
    if _is_admin(user) or subject.owner_id == user.pk:
        return True
    classroom = subject.classroom
    return bool(classroom and user.is_teacher() and classroom.teacher_id == user.pk)


def _copy_level(user, document):
    if document.owner_id == user.pk:
        return 'manage' if document.submission_status == WhiteboardDocument.STATUS_DRAFT else 'view'
    if document.submission_status != WhiteboardDocument.STATUS_DRAFT and is_corrector(user, document.source):
        return 'manage'
    return None


def can(user, document, needed):
    return LEVELS[access_level(user, document)] >= LEVELS[needed]


def visible_documents(user):
    """Documents que l'utilisateur peut au moins consulter."""
    qs = WhiteboardDocument.objects.select_related('owner', 'classroom', 'source')
    if _is_admin(user):
        return qs
    student_classes = ClassroomMember.objects.filter(user=user).values('classroom_id')
    handed_in = Q(submission_status__in=(WhiteboardDocument.STATUS_SUBMITTED, WhiteboardDocument.STATUS_RETURNED))
    return qs.filter(
        Q(owner=user)
        | Q(submission_status='') & (
            Q(members__user=user) | Q(classroom__teacher=user) | Q(classroom_id__in=student_classes, class_visible=True))
        | handed_in & (Q(source__owner=user) | Q(source__classroom__teacher=user))
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
