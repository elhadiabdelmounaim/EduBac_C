"""Django email backend using Brevo's transactional email REST API."""

import logging
import time
from email.utils import parseaddr

import requests
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

from .email_context import email_attempt_id


logger = logging.getLogger(__name__)
BREVO_API_BASE_URL = 'https://api.brevo.com/v3'
BREVO_EMAIL_ENDPOINT = f'{BREVO_API_BASE_URL}/smtp/email'
BREVO_ACCOUNT_ENDPOINT = f'{BREVO_API_BASE_URL}/account'
MAX_RATE_LIMIT_RETRIES = 1
MAX_RETRY_AFTER_SECONDS = 2


class BrevoAPIError(Exception):
    """Safe-to-log API failure; deliberately excludes response bodies and keys."""

    def __init__(self, status_code=None, message=None):
        self.status_code = status_code
        if message is None:
            message = (
                f'L’API Brevo a répondu HTTP {status_code}.'
                if status_code is not None
                else 'La connexion à l’API Brevo a échoué.'
            )
        super().__init__(message)


class BrevoAPIEmailBackend(BaseEmailBackend):
    """Send Django EmailMessage objects through Brevo's HTTPS API."""

    def __init__(self, fail_silently=False, **kwargs):
        super().__init__(fail_silently=fail_silently)
        self.api_key = getattr(settings, 'BREVO_API_KEY', '').strip()
        self.timeout = getattr(settings, 'BREVO_API_TIMEOUT', 15)

    def _headers(self):
        self._require_api_key()
        return {
            'api-key': self.api_key,
            'accept': 'application/json',
            'content-type': 'application/json',
        }

    def _require_api_key(self):
        if not self.api_key:
            raise BrevoAPIError(
                message='BREVO_API_KEY n’est pas configurée.'
            )

    def open(self):
        self._require_api_key()
        return True

    def close(self):
        return None

    def test_connection(self):
        """Validate the API key and HTTPS access without sending an email."""
        try:
            response = requests.get(
                BREVO_ACCOUNT_ENDPOINT,
                headers=self._headers(),
                timeout=self.timeout,
                allow_redirects=False,
            )
        except requests.RequestException:
            raise BrevoAPIError() from None

        if response.status_code != 200:
            raise BrevoAPIError(status_code=response.status_code)
        return True

    def send_messages(self, email_messages):
        if not email_messages:
            return 0

        sent = 0
        for message in email_messages:
            stage = 'api_key_check'
            try:
                self._require_api_key()
                stage = 'payload_build'
                payload = self._build_payload(message)
                stage = 'api_request'
                self._send_message(payload)
            except (BrevoAPIError, TypeError, ValueError) as exc:
                self._log_diagnostic(
                    logging.ERROR,
                    stage=stage,
                    outcome='failed',
                    exception_type=type(exc).__name__,
                    http_status=getattr(exc, 'status_code', None),
                )
                if not self.fail_silently:
                    raise
                logger.warning(
                    'Échec d’envoi via l’API Brevo (%s).',
                    type(exc).__name__,
                )
                continue
            sent += 1
        return sent

    @staticmethod
    def _log_diagnostic(
        level,
        *,
        stage,
        outcome,
        exception_type=None,
        http_status=None,
        retry=None,
    ):
        attempt_id = email_attempt_id.get()
        if attempt_id == '-':
            return
        logger.log(
            level,
            'brevo_email attempt_id=%s stage=%s outcome=%s '
            'http_status=%s retry=%s exception_type=%s',
            attempt_id,
            stage,
            outcome,
            http_status if http_status is not None else '-',
            retry if retry is not None else '-',
            exception_type or '-',
        )

    def _send_message(self, payload):
        for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
            retry_number = attempt + 1
            self._log_diagnostic(
                logging.INFO,
                stage='api_request',
                outcome='started',
                retry=retry_number,
            )
            try:
                response = requests.post(
                    BREVO_EMAIL_ENDPOINT,
                    json=payload,
                    headers=self._headers(),
                    timeout=self.timeout,
                    allow_redirects=False,
                )
            except requests.RequestException as exc:
                # Do not retry an ambiguous timeout: Brevo may already have
                # accepted the message, so retrying could send a duplicate.
                self._log_diagnostic(
                    logging.WARNING,
                    stage='api_request',
                    outcome='network_error',
                    retry=retry_number,
                    exception_type=type(exc).__name__,
                )
                raise BrevoAPIError() from None

            self._log_diagnostic(
                logging.INFO,
                stage='api_response',
                outcome='received',
                http_status=response.status_code,
                retry=retry_number,
            )
            if response.status_code == 201:
                self._log_diagnostic(
                    logging.INFO,
                    stage='api_response',
                    outcome='accepted',
                    http_status=response.status_code,
                    retry=retry_number,
                )
                return

            if (
                response.status_code == 429
                and attempt < MAX_RATE_LIMIT_RETRIES
            ):
                self._log_diagnostic(
                    logging.WARNING,
                    stage='api_response',
                    outcome='retrying_rate_limit',
                    http_status=response.status_code,
                    retry=retry_number,
                )
                self._wait_before_retry(response.headers.get('Retry-After'))
                continue

            self._log_diagnostic(
                logging.ERROR,
                stage='api_response',
                outcome='rejected',
                http_status=response.status_code,
                retry=retry_number,
            )
            raise BrevoAPIError(status_code=response.status_code)

    @staticmethod
    def _wait_before_retry(retry_after):
        try:
            delay = float(retry_after)
        except (TypeError, ValueError):
            delay = 1
        delay = max(0, min(delay, MAX_RETRY_AFTER_SECONDS))
        if delay:
            time.sleep(delay)

    @staticmethod
    def _recipients(addresses):
        recipients = []
        for value in addresses or []:
            name, address = parseaddr(value)
            if not address:
                raise ValueError('Une adresse destinataire est invalide.')
            recipient = {'email': address}
            if name:
                recipient['name'] = name
            recipients.append(recipient)
        return recipients

    def _build_payload(self, message):
        from_value = message.from_email or settings.DEFAULT_FROM_EMAIL
        sender_name, sender_email = parseaddr(from_value)
        if not sender_email:
            raise ValueError('DEFAULT_FROM_EMAIL ne contient pas d’adresse valide.')

        sender = {
            'email': sender_email,
            'name': sender_name or settings.EMAIL_SENDER_NAME,
        }
        recipients = self._recipients(message.to)
        if not recipients:
            raise ValueError('Le message ne contient aucun destinataire.')

        payload = {
            'sender': sender,
            'to': recipients,
            'subject': message.subject or '',
        }

        if message.cc:
            payload['cc'] = self._recipients(message.cc)
        if message.bcc:
            payload['bcc'] = self._recipients(message.bcc)

        reply_to = getattr(message, 'reply_to', None) or []
        if reply_to:
            if len(reply_to) != 1:
                raise ValueError('Brevo ne prend en charge qu’une adresse Reply-To.')
            payload['replyTo'] = self._recipients(reply_to)[0]

        text_content = None
        html_content = None
        body = message.body or ''
        if getattr(message, 'content_subtype', 'plain') == 'html':
            html_content = body
        else:
            text_content = body

        for alternative in getattr(message, 'alternatives', None) or []:
            content, mimetype = alternative
            if mimetype == 'text/html':
                html_content = content
            elif mimetype == 'text/plain':
                text_content = content
            else:
                raise ValueError(
                    'Le format alternatif du message n’est pas pris en charge.'
                )

        if text_content is not None:
            payload['textContent'] = text_content
        if html_content is not None:
            payload['htmlContent'] = html_content

        attachments = getattr(message, 'attachments', None) or []
        if attachments:
            raise ValueError(
                'Les pièces jointes ne sont pas prises en charge par le backend Brevo.'
            )

        extra_headers = getattr(message, 'extra_headers', None) or {}
        if extra_headers:
            payload['headers'] = {
                str(name): str(value)
                for name, value in extra_headers.items()
            }

        return payload
