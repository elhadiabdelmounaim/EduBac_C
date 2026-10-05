"""
Services de notification EduBac (in-app + e-mail).
"""
from .models import Notification


def notify_user(user, title, message, type='system', actor=None, link='', send_email=True):
    return Notification.notify(
        recipient=user,
        title=title,
        message=message,
        type=type,
        actor=actor,
        link=link,
        send_email=send_email,
    )


def notify_quiz_assigned(assignment):
    """Notifie l'élève qu'un quiz lui a été assigné."""
    quiz = assignment.quiz
    deadline = ''
    if assignment.deadline:
        deadline = f" Date limite : {assignment.deadline.strftime('%d/%m/%Y %H:%M')}."
    notify_user(
        user=assignment.student,
        title='Nouveau quiz assigné',
        message=(
            f'Le quiz « {quiz.title} » vous a été assigné '
            f'(leçon : {quiz.lesson.title}).{deadline}'
        ),
        type='quiz_assigned',
        actor=getattr(quiz, 'created_by', None),
        link=f'/quizzes/{quiz.pk}/',
        send_email=True,
    )


def notify_quiz_result(attempt):
    """Notifie l'élève (et éventuellement le prof) du résultat."""
    notify_user(
        user=attempt.student,
        title='Résultat de quiz disponible',
        message=(
            f'Vous avez obtenu {attempt.score}% '
            f'au quiz « {attempt.quiz.title} ».'
        ),
        type='quiz_result',
        link=f'/quizzes/tentative/{attempt.pk}/resultats/',
        send_email=True,
    )
    # Notifier le professeur créateur
    teacher = getattr(attempt.quiz, 'created_by', None)
    if teacher and teacher.id != attempt.student_id:
        notify_user(
            user=teacher,
            title='Résultat élève',
            message=(
                f'{attempt.student.get_full_name()} a obtenu '
                f'{attempt.score}% au quiz « {attempt.quiz.title} ».'
            ),
            type='quiz_result',
            actor=attempt.student,
            link=f'/quizzes/{attempt.quiz.pk}/stats-questions/',
            send_email=True,
        )


def notify_classroom_joined(member):
    """Notifie l'enseignant qu'un élève a rejoint sa classe."""
    classroom = member.classroom
    if classroom.teacher_id:
        notify_user(
            user=classroom.teacher,
            title='Nouvel élève dans la classe',
            message=(
                f'{member.user.get_full_name()} a rejoint '
                f'la classe « {classroom.name} ».'
            ),
            type='classroom',
            actor=member.user,
            link=f'/classrooms/{classroom.pk}/',
            send_email=True,
        )
