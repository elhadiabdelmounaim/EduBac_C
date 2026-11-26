"""Tests navigateur des cours : la lecture se fait en élève d'une classe où les leçons sont
ouvertes (avant la séance, une leçon est verrouillée pour les élèves et les visiteurs)."""
from django.contrib.auth import get_user_model
from django.contrib.sessions.backends.db import SessionStore


def session_eleve_avec_acces(lessons):
    from cahier.models import AccesLecon
    from classrooms.models import Classroom, ClassroomMember
    lessons = list(lessons)
    eleve = get_user_model().objects.create_user(
        username='eleve-lecteur', email='eleve-lecteur@example.test', role='student')
    niveaux = {lesson.course.niveau for lesson in lessons}
    for niveau in niveaux:
        classe = Classroom.objects.create(name=f'Classe {niveau}', niveau=niveau)
        ClassroomMember.objects.create(classroom=classe, user=eleve)
        for lesson in lessons:
            if lesson.course.niveau == niveau:
                AccesLecon.objects.create(classroom=classe, lesson=lesson, decision=AccesLecon.OUVERT)
    session = SessionStore()
    session['user_id'] = eleve.pk
    session.save()
    return session.session_key
