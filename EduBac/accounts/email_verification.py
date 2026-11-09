"""Secure, expiring email-verification links and resend throttling."""
import hashlib
import logging

from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse

from .models import User


logger = logging.getLogger(__name__)
TOKEN_SALT = 'accounts.email-verification.v1'
IP_RATE_LIMIT_WINDOW = 60 * 60


def _digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def verification_expiry_label():
    seconds = settings.EMAIL_VERIFICATION_TOKEN_MAX_AGE
    for unit_seconds, unit_name in (
        (24 * 60 * 60, 'jour'),
        (60 * 60, 'heure'),
        (60, 'minute'),
        (1, 'seconde'),
    ):
        if seconds >= unit_seconds and seconds % unit_seconds == 0:
            count = seconds // unit_seconds
            return f'{count} {unit_name if count == 1 else unit_name + "s"}'
    if seconds >= 60:
        minutes = (seconds + 59) // 60
        return f'{minutes} minute{"s" if minutes != 1 else ""}'
    return f'{seconds} seconde{"s" if seconds != 1 else ""}'


def _claim_send_slot(email, remote_addr):
    ip_key = f'email-verify:ip:{_digest(remote_addr or "unknown")}'
    if not cache.add(ip_key, 1, timeout=IP_RATE_LIMIT_WINDOW):
        try:
            attempts = cache.incr(ip_key)
        except ValueError:
            cache.add(ip_key, 1, timeout=IP_RATE_LIMIT_WINDOW)
            attempts = 1
    else:
        attempts = 1

    if attempts > settings.EMAIL_VERIFICATION_IP_HOURLY_LIMIT:
        return False, None

    email_key = f'email-verify:email:{_digest(email.casefold())}'
    if not cache.add(
        email_key,
        True,
        timeout=settings.EMAIL_VERIFICATION_RESEND_COOLDOWN,
    ):
        return False, email_key
    return True, email_key


def send_verification_email(request, user):
    """Send one signed link, returning sent, rate_limited, or failed."""
    if user.email_verified:
        return 'already_verified'

    allowed, email_key = _claim_send_slot(
        user.email,
        request.META.get('REMOTE_ADDR', ''),
    )
    if not allowed:
        return 'rate_limited'

    try:
        token = signing.dumps(
            {'user_id': user.pk, 'email': user.email},
            salt=TOKEN_SALT,
            compress=True,
        )
        verification_url = request.build_absolute_uri(
            reverse('accounts:confirm_email', kwargs={'token': token})
        )
        context = {
            'user': user,
            'verification_url': verification_url,
            'expiry_label': verification_expiry_label(),
        }
        message = EmailMultiAlternatives(
            subject='Vérifie ton adresse e-mail — EduBac',
            body=render_to_string(
                'accounts/emails/email_verification.txt',
                context,
            ).strip(),
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[user.email],
        )
        message.attach_alternative(
            render_to_string('accounts/emails/email_verification.html', context),
            'text/html',
        )
        if message.send(fail_silently=False) != 1:
            raise RuntimeError('Le fournisseur e-mail n’a confirmé aucun envoi.')
        return 'sent'
    except Exception:
        cache.delete(email_key)
        logger.exception('Échec de l’envoi du message de vérification.')
        return 'failed'


def get_user_from_verification_token(token):
    """Load the token's user and reject stale or changed email addresses."""
    payload = signing.loads(
        token,
        salt=TOKEN_SALT,
        max_age=settings.EMAIL_VERIFICATION_TOKEN_MAX_AGE,
    )
    if not isinstance(payload, dict):
        raise signing.BadSignature('Charge utile invalide.')

    user = User.objects.get(pk=payload.get('user_id'))
    signed_email = payload.get('email')
    if not isinstance(signed_email, str) or signed_email.casefold() != user.email.casefold():
        raise signing.BadSignature('Adresse e-mail modifiée.')
    return user
