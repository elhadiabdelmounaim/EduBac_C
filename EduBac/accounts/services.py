"""Calcul de la progression élève."""
from django.db.models import Avg, Count, Q


def compute_student_progress(user):
    """
    Progression basée sur :
    - quiz terminés avec score >= 50 %
    - moyenne des scores
    Retourne un dict et met à jour StudentProfile.progress.
    """
    from quizzes.models import Attempt, QuizAssignment
    from education.models import Course, Lesson

    profile = getattr(user, 'student_profile', None)
    if not profile:
        return {'progress': 0, 'attempts': 0, 'avg_score': 0, 'assignments_done': 0}

    attempts = Attempt.objects.filter(
        student=user, submitted_at__isnull=False, score__isnull=False
    )
    attempt_count = attempts.count()
    avg = attempts.aggregate(a=Avg('score'))['a'] or 0

    assignments = QuizAssignment.objects.filter(student=user)
    total_assign = assignments.count()
    done_assign = 0
    for a in assignments:
        if Attempt.objects.filter(
            student=user, quiz=a.quiz, submitted_at__isnull=False
        ).exists():
            done_assign += 1

    # Score de progression : 60 % moyenne + 40 % taux de complétion des assignations
    if total_assign > 0:
        completion = (done_assign / total_assign) * 100
    else:
        completion = min(100, attempt_count * 10)  # entraînement libre

    progress = round(0.6 * float(avg) + 0.4 * completion, 1)
    progress = max(0, min(100, progress))

    profile.progress = progress
    profile.save(update_fields=['progress'])

    return {
        'progress': progress,
        'attempts': attempt_count,
        'avg_score': round(float(avg), 1),
        'assignments_total': total_assign,
        'assignments_done': done_assign,
        'niveau': profile.get_niveau_display(),
    }
