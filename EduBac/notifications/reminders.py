"""Rappels de deadline pour les quiz assignés."""
from django.utils import timezone
from datetime import timedelta
from .models import Notification


def send_deadline_reminders():
    """
    Notifie les élèves dont un quiz expire dans moins de 48 h.
    À appeler périodiquement (cron / management command).
    """
    from quizzes.models import QuizAssignment, Attempt
    now = timezone.now()
    soon = now + timedelta(hours=48)
    qs = QuizAssignment.objects.filter(
        deadline__gte=now,
        deadline__lte=soon,
    ).select_related('quiz', 'student')
    created = 0
    for a in qs:
        done = Attempt.objects.filter(
            student=a.student, quiz=a.quiz, submitted_at__isnull=False
        ).exists()
        if done:
            continue
        link = f'/quizzes/{a.quiz_id}/'
        exists = Notification.objects.filter(
            recipient=a.student,
            type='quiz_assigned',
            link=link,
            title__startswith='Rappel',
            created_at__gte=now - timedelta(hours=20),
        ).exists()
        if exists:
            continue
        Notification.notify(
            recipient=a.student,
            title='Rappel — quiz bientôt expiré',
            message=f'Le quiz « {a.quiz.title} » expire le {a.deadline.strftime("%d/%m/%Y %H:%M")}.',
            type='quiz_assigned',
            link=link,
        )
        created += 1
    return created
