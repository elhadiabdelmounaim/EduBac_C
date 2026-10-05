"""Badges, streak, objectifs hebdomadaires."""
from datetime import date, timedelta
from django.utils import timezone
from .models import Badge, UserBadge, DailyActivity


DEFAULT_BADGES = [
    ('first_quiz', 'Premier quiz', 'Tu as terminé ton premier quiz.', '🎯'),
    ('quiz_5', '5 quiz', 'Tu as terminé 5 quiz.', '🔥'),
    ('score_80', 'Score ≥ 80 %', 'Un quiz réussi à 80 % ou plus.', '⭐'),
    ('streak_3', 'Série 3 jours', 'Actif 3 jours de suite.', '📅'),
    ('streak_7', 'Série 7 jours', 'Actif 7 jours de suite.', '🏆'),
]


def ensure_badges():
    for code, name, desc, icon in DEFAULT_BADGES:
        Badge.objects.get_or_create(
            code=code,
            defaults={'name': name, 'description': desc, 'icon': icon},
        )


def record_activity(user, quiz_done=False):
    today = timezone.localdate()
    act, _ = DailyActivity.objects.get_or_create(user=user, day=today)
    if quiz_done:
        act.quiz_count += 1
        act.save(update_fields=['quiz_count'])
    return act


def get_streak(user):
    """Nombre de jours consécutifs avec activité jusqu'à aujourd'hui (ou hier)."""
    days = set(
        DailyActivity.objects.filter(user=user).values_list('day', flat=True)
    )
    if not days:
        return 0
    today = timezone.localdate()
    start = today if today in days else today - timedelta(days=1)
    if start not in days:
        return 0
    streak = 0
    d = start
    while d in days:
        streak += 1
        d -= timedelta(days=1)
    return streak


def award_badge(user, code):
    ensure_badges()
    badge = Badge.objects.filter(code=code).first()
    if not badge:
        return False
    _, created = UserBadge.objects.get_or_create(user=user, badge=badge)
    return created


def check_badges_after_quiz(user, score):
    from quizzes.models import Attempt
    record_activity(user, quiz_done=True)
    n = Attempt.objects.filter(student=user, submitted_at__isnull=False).count()
    earned = []
    if n >= 1 and award_badge(user, 'first_quiz'):
        earned.append('first_quiz')
    if n >= 5 and award_badge(user, 'quiz_5'):
        earned.append('quiz_5')
    if score is not None and float(score) >= 80 and award_badge(user, 'score_80'):
        earned.append('score_80')
    streak = get_streak(user)
    if streak >= 3 and award_badge(user, 'streak_3'):
        earned.append('streak_3')
    if streak >= 7 and award_badge(user, 'streak_7'):
        earned.append('streak_7')
    return earned


def weekly_goal_progress(user, goal=5):
    """Quiz terminés sur les 7 derniers jours."""
    from quizzes.models import Attempt
    start = timezone.now() - timedelta(days=7)
    done = Attempt.objects.filter(
        student=user, submitted_at__isnull=False, submitted_at__gte=start
    ).count()
    return {'done': done, 'goal': goal, 'pct': min(100, int(100 * done / goal)) if goal else 0}
