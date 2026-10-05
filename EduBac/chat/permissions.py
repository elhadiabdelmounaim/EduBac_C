"""Contrôle d'accès Backend pour Prof-Étudiant Chat."""
from classrooms.models import Classroom, ClassroomMember


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
    role = getattr(user, 'role', None)
    if role == 'teacher':
        return classroom.teacher_id == user.id
    if role == 'student':
        return ClassroomMember.objects.filter(classroom=classroom, user=user).exists()
    return False


def classrooms_for_user(user):
    """Liste des classes accessibles pour le chat."""
    if not user or not getattr(user, 'is_authenticated', False):
        return Classroom.objects.none()
    role = getattr(user, 'role', None)
    if role == 'teacher':
        return Classroom.objects.filter(teacher=user, is_active=True).order_by('name')
    if role == 'student':
        ids = ClassroomMember.objects.filter(user=user).values_list('classroom_id', flat=True)
        return Classroom.objects.filter(pk__in=ids, is_active=True).order_by('name')
    return Classroom.objects.none()
