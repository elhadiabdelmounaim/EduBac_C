"""Secure, expiring email-verification links and resend throttling."""
import hashlib
import logging
import math
import uuid

from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from config.email_context import email_attempt_id

from .models import User


logger = logging.getLogger(__name__)
TOKEN_SALT = 'accounts.email-verification.v1'
IP_RATE_LIMIT_WINDOW = 60 * 60
EMAIL_VERIFICATION_IN_FLIGHT_TIMEOUT = 60


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


def _remaining_seconds(duration, started_at, now):
    try:
        elapsed = max(0, now - float(started_at))
    except (TypeError, ValueError):
        elapsed = 0
    return max(0, math.ceil(duration - elapsed))


def _claim_send_slot(email, remote_addr, attempt_id):
    now = timezone.now().timestamp()
    ip_digest = _digest(remote_addr or 'unknown')
    ip_key = f'email-verify:ip:{ip_digest}'
    ip_started_key = f'email-verify:ip-started:{ip_digest}'
    if not cache.add(ip_key, 1, timeout=IP_RATE_LIMIT_WINDOW):
        cache.add(ip_started_key, now, timeout=IP_RATE_LIMIT_WINDOW)
        try:
            attempts = cache.incr(ip_key)
        except ValueError:
            cache.add(ip_key, 1, timeout=IP_RATE_LIMIT_WINDOW)
            attempts = 1
    else:
        cache.set(ip_started_key, now, timeout=IP_RATE_LIMIT_WINDOW)
        attempts = 1

    if attempts > settings.EMAIL_VERIFICATION_IP_HOURLY_LIMIT:
        window_started_at = cache.get(ip_started_key, now)
        remaining = _remaining_seconds(
            IP_RATE_LIMIT_WINDOW,
            window_started_at,
            now,
        )
        logger.info(
            'verification_email attempt_id=%s stage=throttle outcome=blocked '
            'reason=ip_limit remaining_seconds=%s',
            attempt_id,
            remaining,
        )
        return None, 'ip_limit', remaining

    email_digest = _digest(email.casefold())
    sent_key = f'email-verify:last-sent:{email_digest}'
    lock_key = f'email-verify:in-flight:{email_digest}'
    cooldown = settings.EMAIL_VERIFICATION_RESEND_COOLDOWN
    last_sent_at = cache.get(sent_key)

    if last_sent_at is not None and cooldown > 0:
        remaining = _remaining_seconds(cooldown, last_sent_at, now)
        if remaining > 0:
            logger.info(
                'verification_email attempt_id=%s stage=throttle '
                'outcome=blocked reason=email_cooldown remaining_seconds=%s',
                attempt_id,
                remaining,
            )
            return None, 'email_cooldown', remaining
        cache.delete(sent_key)

    if cooldown == 0 and last_sent_at is not None:
        cache.delete(sent_key)

    lock_record = {
        'attempt_id': attempt_id,
        'started_at': now,
    }
    if not cache.add(
        lock_key,
        lock_record,
        timeout=EMAIL_VERIFICATION_IN_FLIGHT_TIMEOUT,
    ):
        existing_lock = cache.get(lock_key)
        remaining = _remaining_seconds(
            EMAIL_VERIFICATION_IN_FLIGHT_TIMEOUT,
            existing_lock.get('started_at') if isinstance(existing_lock, dict) else None,
            now,
        )
        logger.info(
            'verification_email attempt_id=%s stage=throttle '
            'outcome=blocked reason=send_in_progress remaining_seconds=%s',
            attempt_id,
            remaining,
        )
        return None, 'send_in_progress', remaining

    return {
        'sent_key': sent_key,
        'lock_key': lock_key,
        'lock_record': lock_record,
    }, None, 0


def _release_send_lock(reservation, attempt_id):
    try:
        current = cache.get(reservation['lock_key'])
        if (
            isinstance(current, dict)
            and current.get('attempt_id') == attempt_id
        ):
            cache.delete(reservation['lock_key'])
    except Exception as exc:
        logger.warning(
            'verification_email attempt_id=%s stage=lock_release '
            'outcome=failed exception_type=%s',
            attempt_id,
            type(exc).__name__,
        )


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

    reservation, block_reason, remaining = _claim_send_slot(
        user.email,
        request.META.get('REMOTE_ADDR', ''),
        attempt_id,
    )
    if reservation is None:
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
    except Exception as exc:
        _release_send_lock(reservation, attempt_id)
        logger.error(
            'verification_email attempt_id=%s stage=%s outcome=failed exception_type=%s',
            attempt_id,
            stage,
            type(exc).__name__,
        )
        return 'failed'

    logger.info(
        'verification_email attempt_id=%s stage=django_mail_send outcome=backend_returned_one',
        attempt_id,
    )
    cooldown = settings.EMAIL_VERIFICATION_RESEND_COOLDOWN
    if cooldown > 0:
        try:
            cache.set(
                reservation['sent_key'],
                timezone.now().timestamp(),
                timeout=cooldown,
            )
        except Exception as exc:
            # The provider accepted the message. Keep the short in-flight lock
            # until its TTL expires if the cooldown marker cannot be recorded.
            logger.error(
                'verification_email attempt_id=%s stage=cooldown_commit '
                'outcome=failed exception_type=%s',
                attempt_id,
                type(exc).__name__,
            )
        else:
            logger.info(
                'verification_email attempt_id=%s stage=cooldown_commit '
                'outcome=active remaining_seconds=%s',
                attempt_id,
                cooldown,
            )
            _release_send_lock(reservation, attempt_id)
    else:
        _release_send_lock(reservation, attempt_id)
    return 'sent'


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
