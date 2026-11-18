"""
Services de notification EduBac (in-app + e-mail).

Toutes les notifications passent par ici : les liens sont construits avec
reverse(), les événements fréquents sont regroupés, et le choix du canal
(badge, e-mail immédiat, résumé quotidien) suit les préférences du destinataire.
"""
from django.contrib.auth import get_user_model
from django.db.models import Avg, Q
from django.urls import reverse

from .models import Notification


def notify_user(user, title, message, type='system', actor=None, link='', send_email=True, group_key='',
                defer_email=False):
    return Notification.notify(
        recipient=user,
        title=title,
        message=message,
        type=type,
        actor=actor,
        link=link,
        send_email=send_email,
        group_key=group_key,
        defer_email=defer_email,
    )


def _name(user):
    return user.get_full_name() or user.username


def _admins():
    return get_user_model().objects.filter(
        Q(is_staff=True) | Q(is_superuser=True), is_active=True,
    )


# ─── Quiz ────────────────────────────────────────────────────────────────────

def notify_quiz_assigned(assignment):
    """Notifie l'élève qu'un quiz lui a été assigné."""
    quiz = assignment.quiz
    deadline = ''
    if assignment.deadline:
        from django.utils import timezone
        local = timezone.localtime(assignment.deadline)
        deadline = f" Date limite : {local:%d/%m/%Y %H:%M}."
    notify_user(
        user=assignment.student,
        title='Nouveau quiz assigné',
        message=(
            f'Le quiz « {quiz.title} » vous a été assigné '
            f'(leçon : {quiz.lesson.title}).{deadline}'
        ),
        type='quiz_assigned',
        actor=getattr(quiz, 'created_by', None),
        link=reverse('quizzes:detail', args=[quiz.pk]),
        send_email=True,
    )


def notify_quiz_result(attempt):
    """Notifie l'élève de son résultat, et le professeur par une notification regroupée."""
    notify_user(
        user=attempt.student,
        title='Résultat de quiz disponible',
        message=(
            f'Vous avez obtenu {attempt.score}% '
            f'au quiz « {attempt.quiz.title} ».'
        ),
        type='quiz_result',
        link=reverse('quizzes:results', args=[attempt.pk]),
        send_email=True,
    )
    teacher = getattr(attempt.quiz, 'created_by', None)
    if teacher and teacher.id != attempt.student_id:
        notify_teacher_quiz_progress(attempt.quiz, teacher, latest=attempt)


def notify_teacher_quiz_progress(quiz, teacher, latest=None):
    """Une seule notification non lue par quiz : « N élèves ont terminé, moyenne X % »."""
    from quizzes.models import Attempt

    done = Attempt.objects.filter(quiz=quiz, submitted_at__isnull=False)
    finished = done.values('student').distinct().count()
    average = done.aggregate(a=Avg('score'))['a'] or 0
    assigned = quiz.assignments.count()
    progress = f'{finished}/{assigned}' if assigned else str(finished)
    last = f' Dernier : {_name(latest.student)} ({latest.score}%).' if latest else ''
    notify_user(
        user=teacher,
        title=f'Résultats — {quiz.title}',
        message=f'{progress} élève(s) ont terminé ce quiz. Moyenne : {average:.1f} %.{last}',
        type='quiz_result',
        actor=latest.student if latest else None,
        link=reverse('quizzes:question_stats', args=[quiz.pk]),
        send_email=True,
        group_key=f'quiz_results:{quiz.pk}',
    )


def notify_attempt_comment(attempt):
    """L'élève découvre le commentaire du professeur sur sa copie."""
    notify_user(
        user=attempt.student,
        title='Nouveau commentaire du professeur',
        message=f'Votre professeur a commenté votre copie du quiz « {attempt.quiz.title} ».',
        type='comment',
        link=reverse('quizzes:results', args=[attempt.pk]),
        send_email=True,
        group_key=f'comment:{attempt.pk}',
    )


def notify_quiz_published(quiz):
    if quiz.created_by_id:
        notify_user(
            user=quiz.created_by,
            title='Quiz publié',
            message=f'La publication programmée du quiz « {quiz.title} » a eu lieu.',
            type='system',
            link=reverse('quizzes:manage'),
            send_email=False,
        )


# ─── Classes et comptes ──────────────────────────────────────────────────────

def notify_classroom_joined(member):
    """Notifie l'enseignant qu'un élève a rejoint sa classe (regroupé par classe)."""
    classroom = member.classroom
    if classroom.teacher_id:
        notify_user(
            user=classroom.teacher,
            title='Nouvel élève dans la classe',
            message=(
                f'{_name(member.user)} a rejoint '
                f'la classe « {classroom.name} ».'
            ),
            type='classroom',
            actor=member.user,
            link=reverse('classrooms:detail', args=[classroom.pk]),
            send_email=True,
            group_key=f'classroom_joined:{classroom.pk}',
        )


def notify_registration_pending(user):
    """L'administration est prévenue qu'une inscription attend sa validation."""
    from accounts.models import User
    pending = User.objects.filter(role='student', approval_status='pending').count()
    for admin in _admins():
        notify_user(
            user=admin,
            title='Inscriptions en attente',
            message=f'{pending} demande(s) d’inscription attendent votre validation. Dernière : {_name(user)}.',
            type='account',
            actor=user,
            link=reverse('accounts:admin_dashboard'),
            send_email=True,
            # Pas de SMTP pendant l'inscription de l'élève : cloche immédiate, e-mail dans le résumé.
            defer_email=True,
            group_key='registrations_pending',
        )


def notify_registration_approved(user):
    notify_user(
        user=user,
        title='Bienvenue sur EduBac',
        message='Votre inscription a été validée. Vous pouvez maintenant suivre vos cours et vos quiz.',
        type='account',
        link=reverse('accounts:dashboard'),
        send_email=True,
    )


# ─── Messagerie ──────────────────────────────────────────────────────────────

def notify_class_announcement(message):
    """Annonce importante : tous les élèves de la classe (une seule requête)."""
    classroom = message.room.classroom
    recipients = [
        member.user for member in classroom.members.select_related('user')
        if member.user_id != message.sender_id
    ]
    excerpt = (message.body or message.attachment_name or '')[:160]
    Notification.notify_many(
        recipients,
        title=f'Annonce — {classroom.name}',
        message=excerpt or 'Nouvelle annonce importante.',
        type='message',
        actor=message.sender,
        link=reverse('chat:room', args=[classroom.pk]),
    )


def conversation_group_key(kind, conversation_id):
    return f'{kind}:{conversation_id}'


def notify_new_private_message(kind, conversation, message, recipient):
    """Une notification par conversation tant qu'elle n'est pas ouverte."""
    if kind == 'consultation':
        link = reverse('chat:private_room', args=[conversation.pk])
        title = 'Consultation — nouveau message'
    else:
        link = reverse('chat:direct_room', args=[conversation.pk])
        title = 'Nouveau message privé'
    excerpt = message.body[:160] if message.body else (
        'Message vocal' if message.is_voice else 'Pièce jointe'
    )
    notify_user(
        user=recipient,
        title=title,
        message=f'{_name(message.sender)} : {excerpt}',
        type='message',
        actor=message.sender,
        link=link,
        send_email=True,
        group_key=conversation_group_key(kind, conversation.pk),
    )


def notify_report(report, reviewers):
    for reviewer in reviewers:
        notify_user(
            user=reviewer,
            title='Messages signalés',
            message=f'Nouveau signalement : {report.get_reason_display()}. À traiter dans la modération.',
            type='moderation',
            link=reverse('chat:moderation'),
            send_email=True,
            group_key='chat_reports',
        )


def notify_whiteboard_share(share):
    Notification.notify_many(
        [member.user for member in share.classroom.members.select_related('user')],
        title='Whiteboard partagé',
        message=f'« {share.title} » a été partagé avec la classe {share.classroom.name}.',
        type='classroom',
        actor=share.teacher,
        link=reverse('whiteboard:share_view', args=[share.pk]),
    )
