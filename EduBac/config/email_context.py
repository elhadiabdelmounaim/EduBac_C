"""Request-local, non-sensitive correlation data for email diagnostics."""

from contextvars import ContextVar


email_attempt_id = ContextVar('edubac_email_attempt_id', default='-')
