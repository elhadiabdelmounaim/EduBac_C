"""Opt-in, redacted diagnostics for Django email delivery failures."""

import re
import traceback

from django.conf import settings


_URL_RE = re.compile(r'https?://\S+', re.IGNORECASE)
_EMAIL_RE = re.compile(
    r'\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b',
    re.IGNORECASE,
)
_IP_RE = re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b')
_TOKEN_RE = re.compile(r'\b[A-Za-z0-9_-]{24,}\b')


def _redact_diagnostic_text(value):
    text = str(value)
    for secret in (
        getattr(settings, 'EMAIL_HOST_PASSWORD', ''),
        getattr(settings, 'EMAIL_HOST_USER', ''),
    ):
        if secret:
            text = text.replace(secret, '[redacted]')
    text = _URL_RE.sub('[URL redacted]', text)
    text = _EMAIL_RE.sub('[email redacted]', text)
    text = _IP_RE.sub('[IP redacted]', text)
    text = _TOKEN_RE.sub('[token redacted]', text)
    return text


def log_email_exception(logger, *, event, stage, exc, attempt_id='-'):
    """Log only the exception type by default; opt-in diagnostics are redacted."""
    prefix = (
        'email_diagnostic event=%s attempt_id=%s stage=%s '
        'outcome=failed exception_type=%s'
    )
    values = (event, attempt_id, stage, type(exc).__name__)
    if not getattr(settings, 'EMAIL_DIAGNOSTIC_TRACEBACK', False):
        logger.error(prefix, *values)
        return

    try:
        safe_message = _redact_diagnostic_text(str(exc))[:1200]
    except Exception:
        safe_message = '[exception message unavailable]'
    try:
        safe_traceback = _redact_diagnostic_text(
            ''.join(traceback.format_exception(
                type(exc),
                exc,
                exc.__traceback__,
                chain=True,
            ))
        )[:8000]
    except Exception:
        safe_traceback = '[traceback unavailable]'

    logger.error(
        '%s exception_message=%s traceback=%s',
        prefix % values,
        safe_message,
        safe_traceback,
    )
