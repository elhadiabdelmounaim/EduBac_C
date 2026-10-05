"""Permissions liées aux classes."""


def teacher_owns_classroom(user, classroom):
    return user.is_authenticated and getattr(user, 'role', None) == 'teacher' and classroom.teacher_id == getattr(user, 'id', None)


def student_in_classroom(user, classroom):
    if not user.is_authenticated:
        return False
    return classroom.members.filter(user=user).exists()


def teacher_can_see_student(teacher, student):
    """True si l'élève est dans une classe du professeur."""
    if not teacher.is_authenticated or getattr(teacher, 'role', None) != 'teacher':
        return False
    return student.classroom_memberships.filter(classroom__teacher=teacher).exists()
