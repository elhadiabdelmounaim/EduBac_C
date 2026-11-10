"""Secure, expiring email-verification links and resend throttling."""
import hashlib
import logging
import uuid

from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse

from config.email_context import email_attempt_id

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


def send_verification_email(request, user, *, attempt_id=None):
    """Send one signed link, returning sent, rate_limited, or failed."""
    attempt_id = attempt_id or uuid.uuid4().hex[:12]
    context_token = email_attempt_id.set(attempt_id)
    try:
        return _send_verification_email(request, user, attempt_id)
    finally:
        email_attempt_id.reset(context_token)


def _send_verification_email(request, user, attempt_id):
    logger.info(
        'verification_email attempt_id=%s stage=start outcome=started',
        attempt_id,
    )
    if user.email_verified:
        logger.info(
            'verification_email attempt_id=%s stage=eligibility outcome=already_verified',
            attempt_id,
        )
        return 'already_verified'

    allowed, email_key = _claim_send_slot(
        user.email,
        request.META.get('REMOTE_ADDR', ''),
    )
    if not allowed:
        reason = 'ip_limit' if email_key is None else 'email_cooldown'
        logger.info(
            'verification_email attempt_id=%s stage=throttle outcome=blocked reason=%s',
            attempt_id,
            reason,
        )
        return 'rate_limited'

    stage = 'token_generation'
    try:
        token = signing.dumps(
            {'user_id': user.pk, 'email': user.email},
            salt=TOKEN_SALT,
            compress=True,
        )
        logger.info(
            'verification_email attempt_id=%s stage=token_generation outcome=complete',
            attempt_id,
        )
        stage = 'verification_url'
        verification_url = request.build_absolute_uri(
            reverse('accounts:confirm_email', kwargs={'token': token})
        )
        logger.info(
            'verification_email attempt_id=%s stage=verification_url outcome=complete',
            attempt_id,
        )
        context = {
            'user': user,
            'verification_url': verification_url,
            'expiry_label': verification_expiry_label(),
        }
        stage = 'template_rendering'
        text_body = render_to_string(
            'accounts/emails/email_verification.txt',
            context,
        ).strip()
        html_body = render_to_string(
            'accounts/emails/email_verification.html',
            context,
        )
        logger.info(
            'verification_email attempt_id=%s stage=template_rendering outcome=complete',
            attempt_id,
        )
        stage = 'message_construction'
        message = EmailMultiAlternatives(
            subject='Vérifie ton adresse e-mail — EduBac',
            body=text_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[user.email],
        )
        message.attach_alternative(
            html_body,
            'text/html',
        )
        logger.info(
            'verification_email attempt_id=%s stage=message_construction outcome=complete',
            attempt_id,
        )
        stage = 'django_mail_send'
        logger.info(
            'verification_email attempt_id=%s stage=django_mail_send outcome=started',
            attempt_id,
        )
        sent = message.send(fail_silently=False)
        if sent != 1:
            raise RuntimeError('Le fournisseur e-mail n’a confirmé aucun envoi.')
        logger.info(
            'verification_email attempt_id=%s stage=django_mail_send outcome=backend_returned_one',
            attempt_id,
        )
        return 'sent'
    except Exception as exc:
        cache.delete(email_key)
        logger.error(
            'verification_email attempt_id=%s stage=%s outcome=failed exception_type=%s',
            attempt_id,
            stage,
            type(exc).__name__,
        )
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
