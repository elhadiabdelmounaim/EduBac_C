from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

import requests
from django.core.mail import EmailMultiAlternatives, EmailMessage
from django.core.management import call_command
from django.test import SimpleTestCase, override_settings

from config.email_context import email_attempt_id
from config.email_backend import (
    BREVO_ACCOUNT_ENDPOINT,
    BREVO_EMAIL_ENDPOINT,
    BrevoAPIEmailBackend,
    BrevoAPIError,
)


@override_settings(
    BREVO_API_KEY='test-api-key',
    BREVO_API_TIMEOUT=7,
    DEFAULT_FROM_EMAIL='EduBac <sender@example.test>',
    EMAIL_SENDER_NAME='EduBac',
)
class BrevoAPIEmailBackendTests(SimpleTestCase):
    def test_connection_uses_account_endpoint_and_private_api_header(self):
        with patch(
            'config.email_backend.requests.get',
            return_value=SimpleNamespace(status_code=200),
        ) as get:
            self.assertTrue(BrevoAPIEmailBackend().test_connection())

        get.assert_called_once_with(
            BREVO_ACCOUNT_ENDPOINT,
            headers={
                'api-key': 'test-api-key',
                'accept': 'application/json',
                'content-type': 'application/json',
            },
            timeout=7,
            allow_redirects=False,
        )

    def test_multipart_message_preserves_sender_recipients_and_templates(self):
        message = EmailMultiAlternatives(
            subject='Vérifie ton adresse',
            body='Version texte',
            from_email='EduBac <sender@example.test>',
            to=['Amina <amina@example.test>'],
            cc=['teacher@example.test'],
        )
        message.attach_alternative('<p>Version HTML</p>', 'text/html')
        response = SimpleNamespace(status_code=201, headers={})

        with patch(
            'config.email_backend.requests.post',
            return_value=response,
        ) as post:
            sent = BrevoAPIEmailBackend().send_messages([message])

        self.assertEqual(sent, 1)
        self.assertEqual(post.call_args.args, (BREVO_EMAIL_ENDPOINT,))
        self.assertEqual(
            post.call_args.kwargs['json'],
            {
                'sender': {'email': 'sender@example.test', 'name': 'EduBac'},
                'to': [{'email': 'amina@example.test', 'name': 'Amina'}],
                'cc': [{'email': 'teacher@example.test'}],
                'subject': 'Vérifie ton adresse',
                'textContent': 'Version texte',
                'htmlContent': '<p>Version HTML</p>',
            },
        )
        self.assertEqual(post.call_args.kwargs['timeout'], 7)
        self.assertFalse(post.call_args.kwargs['allow_redirects'])

    def test_only_http_201_counts_as_sent(self):
        response = SimpleNamespace(status_code=202, headers={})
        with patch(
            'config.email_backend.requests.post',
            return_value=response,
        ):
            with self.assertRaises(BrevoAPIError) as raised:
                BrevoAPIEmailBackend().send_messages(
                    [EmailMessage('Subject', 'Body', to=['to@example.test'])]
                )

        self.assertEqual(raised.exception.status_code, 202)

    def test_rate_limit_gets_one_bounded_retry(self):
        responses = [
            SimpleNamespace(status_code=429, headers={'Retry-After': '99'}),
            SimpleNamespace(status_code=201, headers={}),
        ]
        with (
            patch(
                'config.email_backend.requests.post',
                side_effect=responses,
            ) as post,
            patch('config.email_backend.time.sleep') as sleep,
        ):
            sent = BrevoAPIEmailBackend().send_messages(
                [EmailMessage('Subject', 'Body', to=['to@example.test'])]
            )

        self.assertEqual(sent, 1)
        self.assertEqual(post.call_count, 2)
        sleep.assert_called_once_with(2)

    def test_http_errors_do_not_expose_response_body_or_count_as_sent(self):
        response = SimpleNamespace(
            status_code=401,
            headers={},
            text='private provider response',
        )
        trace_token = email_attempt_id.set('trace-http-401')
        with patch(
            'config.email_backend.requests.post',
            return_value=response,
        ):
            try:
                with self.assertLogs(
                    'config.email_backend',
                    level='INFO',
                ) as diagnostics:
                    with self.assertRaises(BrevoAPIError) as raised:
                        BrevoAPIEmailBackend().send_messages(
                            [EmailMessage(
                                'Private subject',
                                'Private body',
                                to=['private-recipient@example.test'],
                            )]
                        )
            finally:
                email_attempt_id.reset(trace_token)

        self.assertEqual(raised.exception.status_code, 401)
        self.assertNotIn('private provider response', str(raised.exception))
        log_output = '\n'.join(diagnostics.output)
        self.assertIn('http_status=401', log_output)
        self.assertIn('outcome=rejected', log_output)
        self.assertNotIn('private-recipient@example.test', log_output)
        self.assertNotIn('Private subject', log_output)
        self.assertNotIn('Private body', log_output)

    def test_accepted_response_logs_http_status_without_message_data(self):
        response = SimpleNamespace(status_code=201, headers={})
        trace_token = email_attempt_id.set('trace-http-201')
        try:
            with (
                patch(
                    'config.email_backend.requests.post',
                    return_value=response,
                ),
                self.assertLogs(
                    'config.email_backend',
                    level='INFO',
                ) as diagnostics,
            ):
                sent = BrevoAPIEmailBackend().send_messages(
                    [EmailMessage(
                        'Private success subject',
                        'Private success body',
                        to=['private-success@example.test'],
                    )]
                )
        finally:
            email_attempt_id.reset(trace_token)

        self.assertEqual(sent, 1)
        log_output = '\n'.join(diagnostics.output)
        self.assertIn('http_status=201', log_output)
        self.assertIn('outcome=accepted', log_output)
        self.assertNotIn('private-success@example.test', log_output)
        self.assertNotIn('Private success subject', log_output)
        self.assertNotIn('Private success body', log_output)

    def test_network_failure_is_safe_and_not_retried(self):
        with patch(
            'config.email_backend.requests.post',
            side_effect=requests.Timeout('sensitive request details'),
        ) as post:
            with self.assertRaises(BrevoAPIError) as raised:
                BrevoAPIEmailBackend().send_messages(
                    [EmailMessage('Subject', 'Body', to=['to@example.test'])]
                )

        self.assertNotIn('sensitive request details', str(raised.exception))
        post.assert_called_once()

    @override_settings(BREVO_API_KEY='')
    def test_missing_key_fails_explicitly(self):
        with self.assertRaises(BrevoAPIError) as raised:
            BrevoAPIEmailBackend().send_messages(
                [EmailMessage('Subject', 'Body', to=['to@example.test'])]
            )
        self.assertIn('BREVO_API_KEY', str(raised.exception))

    def test_fail_silently_returns_zero_for_http_failure(self):
        response = SimpleNamespace(status_code=403, headers={})
        with patch(
            'config.email_backend.requests.post',
            return_value=response,
        ):
            sent = BrevoAPIEmailBackend(fail_silently=True).send_messages(
                [EmailMessage('Subject', 'Body', to=['to@example.test'])]
            )
        self.assertEqual(sent, 0)

    def test_empty_message_list_does_not_call_api(self):
        with patch('config.email_backend.requests.post') as post:
            self.assertEqual(
                BrevoAPIEmailBackend().send_messages([]),
                0,
            )
        post.assert_not_called()

    def test_management_command_can_send_a_real_test_to_verified_sender(self):
        output = StringIO()
        with (
            patch(
                'config.email_backend.requests.get',
                return_value=SimpleNamespace(status_code=200),
            ) as get,
            patch(
                'config.email_backend.requests.post',
                return_value=SimpleNamespace(status_code=201, headers={}),
            ) as post,
        ):
            call_command(
                'check_brevo_email',
                '--send-test',
                stdout=output,
            )

        self.assertEqual(get.call_count, 1)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(
            post.call_args.kwargs['json']['to'],
            [{'email': 'sender@example.test'}],
        )
        self.assertIn('Connexion à l’API Brevo vérifiée', output.getvalue())
        self.assertIn('E-mail de test accepté par Brevo', output.getvalue())
