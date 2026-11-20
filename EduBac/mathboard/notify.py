"""Notifications du tableau mathématique (dans l'application et sur le téléphone).

Aucun e-mail : EduBac fonctionne sans adresse électronique pour les élèves.
Une notification par document et par destinataire (regroupée) : un partage
modifié plusieurs fois ne multiplie pas les alertes.
"""
from django.urls import reverse
from django.utils import timezone

from notifications.models import Notification


def _name(user):
    return user.get_full_name() or user.username


def _link(document):
    return reverse('mathboard:editor', args=[document.pk])


def _due(document):
    if not document.due_at:
        return ''
    return f' À rendre avant le {timezone.localtime(document.due_at):%d/%m/%Y à %H:%M}.'


def classroom_shared(document, actor):
    """Document partagé avec une classe (ou devenu un travail à rendre)."""
    classroom = document.classroom
    if classroom is None:
        return
    students = [m.user for m in classroom.members.select_related('user') if m.user.is_active and m.user.pk != actor.pk]
    if not students:
        return
    if document.accepts_submissions:
        title = 'Travail à rendre'
        message = f'« {document.title} » ({classroom.name}) : ouvrez-le et cliquez sur « Faire ce travail ».{_due(document)}'
    else:
        title = 'Tableau mathématique partagé'
        message = f'« {document.title} » a été partagé avec la classe {classroom.name}.'
    Notification.notify_many(students, title=title, message=message, type='classroom', actor=actor,
                             link=_link(document), group_key=f'mathboard_share:{document.pk}')


def member_invited(member, actor):
    Notification.notify(
        member.user, title='Invitation à un tableau',
        message=f'{_name(actor)} vous a invité sur « {member.document.title} » ({member.get_role_display().lower()}).',
        type='classroom', actor=actor, link=_link(member.document), send_email=False,
        group_key=f'mathboard_member:{member.document_id}')


def copy_submitted(copy, correctors):
    for teacher in correctors:
        Notification.notify(
            teacher, title='Travail rendu',
            message=f'{_name(copy.owner)} a rendu « {copy.source.title if copy.source else copy.title} ».',
            type='classroom', actor=copy.owner, link=_link(copy), send_email=False,
            group_key=f'mathboard_submitted:{copy.source_id}')


def copy_returned(copy, actor, redo):
    if redo:
        title, message = 'Travail à reprendre', f'« {copy.title} » : votre professeur vous demande de le reprendre.'
    else:
        grade = f' Note : {copy.grade}.' if copy.grade else ''
        title, message = 'Travail corrigé', f'« {copy.title} » a été corrigé.{grade}'
    Notification.notify(copy.owner, title=title, message=message, type='classroom', actor=actor,
                        link=_link(copy), send_email=False, group_key=f'mathboard_returned:{copy.pk}')
