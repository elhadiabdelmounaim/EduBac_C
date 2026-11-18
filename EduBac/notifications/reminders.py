"""Rappels de date limite (élèves) et alertes de quiz non faits (professeurs)."""
from datetime import timedelta

from django.db.models import Exists, OuterRef
from django.urls import reverse
from django.utils import timezone

from .models import Notification


def _unfinished(assignments):
    from quizzes.models import Attempt
    return assignments.annotate(
        done=Exists(Attempt.objects.filter(
            student=OuterRef('student'), quiz=OuterRef('quiz'), submitted_at__isnull=False,
        )),
    ).filter(done=False)


def send_deadline_reminders():
    """
    Notifie les élèves dont un quiz expire dans moins de 48 h (une fois par quiz).
    À appeler périodiquement (cron / management command).
    """
    from quizzes.models import QuizAssignment
    now = timezone.now()
    qs = _unfinished(QuizAssignment.objects.filter(
        deadline__gte=now,
        deadline__lte=now + timedelta(hours=48),
        quiz__status='published',
    )).select_related('quiz', 'student')
    created = 0
    for assignment in qs:
        key = f'reminder:{assignment.pk}'
        if Notification.objects.filter(recipient=assignment.student, group_key=key).exists():
            continue
        local = timezone.localtime(assignment.deadline)
        Notification.notify(
            recipient=assignment.student,
            title='Rappel — quiz bientôt expiré',
            message=f'Le quiz « {assignment.quiz.title} » expire le {local:%d/%m/%Y à %H:%M}.',
            type='quiz_assigned',
            link=reverse('quizzes:detail', args=[assignment.quiz_id]),
            group_key=key,
        )
        created += 1
    return created


def send_missed_deadline_alerts():
    """
    Prévient le professeur, une fois par quiz et par date limite, du nombre
    d'élèves qui n'ont pas fait le quiz dans les temps (dernières 72 h).
    """
    from quizzes.models import QuizAssignment
    now = timezone.now()
    missed = _unfinished(QuizAssignment.objects.filter(
        deadline__lt=now,
        deadline__gte=now - timedelta(hours=72),
        quiz__created_by__isnull=False,
    )).select_related('quiz', 'quiz__created_by', 'student')
    by_quiz = {}
    for assignment in missed:
        by_quiz.setdefault((assignment.quiz, assignment.deadline.date()), []).append(assignment.student)
    created = 0
    for (quiz, day), students in by_quiz.items():
        key = f'quiz_missed:{quiz.pk}:{day.isoformat()}'
        if Notification.objects.filter(recipient=quiz.created_by, group_key=key).exists():
            continue
        names = ', '.join(s.get_full_name() or s.username for s in students[:5])
        more = f' et {len(students) - 5} autre(s)' if len(students) > 5 else ''
        Notification.notify(
            recipient=quiz.created_by,
            title=f'Quiz non fait — {quiz.title}',
            message=f'{len(students)} élève(s) n’ont pas fait le quiz avant la date limite : {names}{more}.',
            type='quiz_missed',
            link=reverse('quizzes:student_results') + f'?quiz={quiz.pk}',
            group_key=key,
        )
        created += 1
    return created
