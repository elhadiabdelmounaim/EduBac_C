"""
Signaux : création automatique de notifications.
"""
from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender='quizzes.QuizAssignment')
def on_quiz_assigned(sender, instance, created, **kwargs):
    if created:
        from .services import notify_quiz_assigned
        notify_quiz_assigned(instance)


@receiver(post_save, sender='quizzes.Attempt')
def on_attempt_submitted(sender, instance, **kwargs):
    # Notifier uniquement quand le score est calculé et soumis
    if instance.submitted_at and instance.score is not None:
        from .services import notify_quiz_result
        # Éviter les doublons : une seule notif par tentative
        from .models import Notification
        already = Notification.objects.filter(
            recipient=instance.student,
            type='quiz_result',
            link=f'/quizzes/tentative/{instance.pk}/resultats/',
        ).exists()
        if not already:
            notify_quiz_result(instance)


@receiver(post_save, sender='classrooms.ClassroomMember')
def on_classroom_joined(sender, instance, created, **kwargs):
    if created:
        from .services import notify_classroom_joined
        notify_classroom_joined(instance)
