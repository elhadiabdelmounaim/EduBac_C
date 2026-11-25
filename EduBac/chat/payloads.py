"""Représentation JSON des messages de consultation et des messages individuels."""
from datetime import datetime

from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime


def context_payload(message):
    """Leçon ou question de quiz à laquelle se rapporte un message de consultation."""
    question = getattr(message, 'question', None) if getattr(message, 'question_id', None) else None
    if question is not None:
        quiz = question.quiz
        return {
            'kind': 'question',
            'label': f'Question {question.order} — {quiz.title}',
            'text': question.text[:400],
            'url': reverse('education:lesson_detail', args=[quiz.lesson_id]),
        }
    lesson = getattr(message, 'lesson', None) if getattr(message, 'lesson_id', None) else None
    if lesson is not None:
        return {
            'kind': 'lesson',
            'label': f'Leçon : {lesson.title}',
            'text': '',
            'url': reverse('education:lesson_detail', args=[lesson.pk]),
        }
    return None


def reply_payload(message):
    """Citation du message auquel on répond (jamais le contenu d'un message supprimé)."""
    if not getattr(message, 'reply_to_id', None):
        return None
    cite = message.reply_to
    if cite is None:
        return None
    return {
        'id': cite.pk,
        'body': (
            'Message supprimé' if cite.is_deleted
            else (cite.body or cite.attachment_name or ('Message vocal' if cite.is_voice else 'Message'))[:120]
        ),
        'sender_name': cite.sender.get_full_name() or cite.sender.username,
    }


def _reactions_resume(message, user):
    from .reactions import resume
    return resume(message, user)


def conversation_message_payload(message, user, attachment_route):
    sender = message.sender
    deleted = message.is_deleted
    has_attachment = bool(message.attachment) and not deleted
    return {
        'id': message.pk,
        'body': '' if deleted else message.body,
        'sender_id': sender.pk,
        'sender_name': sender.get_full_name() or sender.username,
        'created_at': message.created_at.isoformat(),
        'time_display': timezone.localtime(message.created_at).strftime('%d/%m/%Y %H:%M'),
        'is_read': message.read_at is not None,
        'is_voice': message.is_voice and not deleted,
        'is_image': message.is_image and has_attachment,
        'attachment_url': (
            reverse(attachment_route, args=[message.pk]) if has_attachment else ''
        ),
        'attachment_name': message.attachment_name if has_attachment else '',
        'context': None if deleted else context_payload(message),
        'reply_to': None if deleted else reply_payload(message),
        'reactions': _reactions_resume(message, user),
        **message.moderation_payload(user),
    }


def parse_since(raw):
    """Horodatage ISO renvoyé par le serveur lors de la synchronisation précédente."""
    if not raw:
        return None
    value = parse_datetime(raw)
    if value is None:
        try:
            value = datetime.fromisoformat(raw)
        except ValueError:
            return None
    if timezone.is_naive(value):
        value = timezone.make_aware(value)
    return value
