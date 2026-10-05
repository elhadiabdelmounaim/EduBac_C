"""
Envoi d'e-mails EduBac pour les notifications importantes.
"""
import logging
from django.conf import settings
from django.core.mail import EmailMultiAlternatives, send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags

logger = logging.getLogger(__name__)


def email_enabled():
    return getattr(settings, 'EMAIL_NOTIFICATIONS_ENABLED', True)


def absolute_url(path: str) -> str:
    base = getattr(settings, 'SITE_URL', 'http://127.0.0.1:8000').rstrip('/')
    if not path:
        return base
    if path.startswith('http'):
        return path
    return f"{base}/{path.lstrip('/')}"


def send_notification_email(recipient, title, message, link='', type_code='system'):
    """
    Envoie un e-mail HTML + texte au destinataire.
    Ne lève pas d'exception vers l'appelant (log uniquement).
    """
    if not email_enabled():
        return False
    email = getattr(recipient, 'email', '') or ''
    if not email or '@' not in email:
        logger.debug('Pas d’e-mail pour %s', getattr(recipient, 'username', recipient))
        return False

    context = {
        'title': title,
        'message': message,
        'link': absolute_url(link) if link else '',
        'type_code': type_code,
        'recipient_name': recipient.get_full_name() or recipient.username,
        'site_name': 'EduBac',
    }
    try:
        html = render_to_string('notifications/email/notification.html', context)
        text = render_to_string('notifications/email/notification.txt', context)
    except Exception:
        text = f"{title}\n\n{message}\n"
        if link:
            text += f"\nLien : {absolute_url(link)}\n"
        html = None

    from_email = settings.DEFAULT_FROM_EMAIL
    try:
        if html:
            msg = EmailMultiAlternatives(title, text, from_email, [email])
            msg.attach_alternative(html, 'text/html')
            msg.send(fail_silently=False)
        else:
            send_mail(title, text, from_email, [email], fail_silently=False)
        logger.info('E-mail envoyé à %s : %s', email, title)
        return True
    except Exception as e:
        logger.exception('Échec envoi e-mail à %s : %s', email, e)
        return False
