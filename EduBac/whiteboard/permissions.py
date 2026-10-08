"""Permissions Whiteboard — basées sur Classroom existant."""
from classrooms.models import Classroom, ClassroomMember


def _user(request):
    return getattr(request, 'edubac_user', None) or request.user


def user_can_access_classroom(user, classroom) -> bool:
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    if getattr(user, 'is_superuser', False):
        return True
    if getattr(user, 'role', '') == 'teacher' and classroom.teacher_id == user.id:
        return True
    if getattr(user, 'role', '') == 'student':
        return ClassroomMember.objects.filter(classroom=classroom, user=user).exists()
    return False


def user_can_edit_board(user, board) -> bool:
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    if getattr(user, 'role', '') == 'student':
        return False
    if getattr(user, 'is_superuser', False):
        return True
    if board.created_by_id == user.id:
        return True
    if board.classroom_id:
        if getattr(user, 'role', '') == 'teacher' and board.classroom.teacher_id == user.id:
            return True
        if getattr(user, 'role', '') == 'student' and board.students_can_edit:
            return ClassroomMember.objects.filter(
                classroom=board.classroom, user=user
            ).exists()
    elif getattr(user, 'role', '') == 'teacher' and board.created_by_id == user.id:
        return True
    return False


def user_can_access_board(user, board) -> bool:
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    if getattr(user, 'is_superuser', False):
        return True
    if board.created_by_id == user.id:
        return True
    if board.classroom_id:
        return user_can_access_classroom(user, board.classroom)
    # Tableau perso enseignant sans classe
    return board.created_by_id == user.id
