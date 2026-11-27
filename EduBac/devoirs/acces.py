"""Qui gère, qui voit : un devoir appartient à son professeur (et aux administrateurs) ;
un élève voit les devoirs de ses classes, et seulement les fichiers visibles."""
from django.db.models import Q

from classrooms.models import Classroom, ClassroomMember

from .models import Devoir


def est_admin(user):
    return bool(getattr(user, 'is_staff', False) or getattr(user, 'is_superuser', False))


def classes_gerees(user):
    """Classes actives que ce professeur peut choisir pour un devoir."""
    classes = Classroom.objects.filter(is_active=True)
    if not est_admin(user):
        classes = classes.filter(teacher=user)
    return classes.order_by('niveau', 'name')


def devoirs_geres(user):
    if est_admin(user):
        return Devoir.objects.all()
    return Devoir.objects.filter(teacher=user)


def devoirs_de_l_eleve(user):
    classes = ClassroomMember.objects.filter(user=user, classroom__is_active=True).values('classroom_id')
    return Devoir.objects.filter(classes__in=classes).distinct()


def peut_gerer(user, devoir):
    return bool(user and user.is_teacher() and (est_admin(user) or devoir.teacher_id == user.pk))


def peut_voir(user, devoir):
    if not user:
        return False
    if peut_gerer(user, devoir):
        return True
    return devoir.classes.filter(
        Q(members__user=user), is_active=True,
    ).exists()


def eleves_des_classes(classes):
    """Élèves (sans doublon) des classes données."""
    from accounts.models import User
    ids = ClassroomMember.objects.filter(classroom__in=classes).values('user_id')
    return User.objects.filter(pk__in=ids, role='student')
