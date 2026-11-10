from logging import getLogger

from django.test import SimpleTestCase, override_settings

from config.email_diagnostics import log_email_exception


@override_settings(
    EMAIL_DIAGNOSTIC_TRACEBACK=True,
    EMAIL_HOST_USER='sender@example.test',
    EMAIL_HOST_PASSWORD='private-app-password',
)
class EmailDiagnosticsTests(SimpleTestCase):
    def test_opt_in_diagnostic_redacts_secrets_addresses_urls_and_tokens(self):
        token = 'A' * 40
        try:
            raise ValueError(
                'Invalid address sender@example.test; '
                'recipient recipient@example.test; '
                'password private-app-password; '
                f'link https://edubac.test/confirm/{token}'
            )
        except ValueError as exc:
            with self.assertLogs('test.email_diagnostics', level='ERROR') as logs:
                log_email_exception(
                    getLogger('test.email_diagnostics'),
                    event='verification_email',
                    attempt_id='test-attempt',
                    stage='django_mail_send',
                    exc=exc,
                )

        output = '\n'.join(logs.output)
        self.assertIn('exception_type=ValueError', output)
        self.assertIn('Invalid address', output)
        self.assertIn('traceback=', output)
        for private_value in (
            'sender@example.test',
            'recipient@example.test',
            'private-app-password',
            token,
            'https://edubac.test',
        ):
            self.assertNotIn(private_value, output)
        self.assertIn('[email redacted]', output)
        self.assertIn('[URL redacted]', output)

    @override_settings(EMAIL_DIAGNOSTIC_TRACEBACK=False)
    def test_default_diagnostic_logs_type_without_message_or_traceback(self):
        try:
            raise ValueError('private-app-password sender@example.test')
        except ValueError as exc:
            with self.assertLogs('test.email_diagnostics', level='ERROR') as logs:
                log_email_exception(
                    getLogger('test.email_diagnostics'),
                    event='verification_email',
                    attempt_id='test-attempt',
                    stage='django_mail_send',
                    exc=exc,
                )

        output = '\n'.join(logs.output)
        self.assertIn('exception_type=ValueError', output)
        self.assertNotIn('private-app-password', output)
        self.assertNotIn('sender@example.test', output)
        self.assertNotIn('traceback=', output)
