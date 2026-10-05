"""Context processors EduBac — badges sidebar / navbar."""
from django.utils import timezone
from datetime import datetime


def student_sidebar(request):
    ctx = {
        'student_has_class': False,
        'new_quiz_assignments_count': 0,
    }
    user = getattr(request, 'edubac_user', None) or getattr(request, 'user', None)
    if not user or not getattr(user, 'is_authenticated', False):
        return ctx
    if getattr(user, 'role', None) != 'student':
        return ctx
    try:
        from classrooms.models import ClassroomMember
        from quizzes.models import QuizAssignment

        ctx['student_has_class'] = ClassroomMember.objects.filter(user=user).exists()
        if not ctx['student_has_class']:
            return ctx

        qs = QuizAssignment.objects.filter(student=user)
        seen_raw = request.session.get('quiz_assignments_seen_at')
        if seen_raw:
            try:
                seen_at = datetime.fromisoformat(seen_raw)
                if timezone.is_naive(seen_at):
                    seen_at = timezone.make_aware(seen_at)
                qs = qs.filter(assigned_at__gt=seen_at)
            except (ValueError, TypeError):
                pass
        # Unread-ish: assignments after last visit to page, not yet completed
        from quizzes.models import Attempt
        count = 0
        for a in qs.select_related('quiz')[:50]:
            done = Attempt.objects.filter(
                student=user, quiz=a.quiz, submitted_at__isnull=False
            ).exists()
            if not done:
                count += 1
        ctx['new_quiz_assignments_count'] = count
    except Exception:
        pass
    return ctx
