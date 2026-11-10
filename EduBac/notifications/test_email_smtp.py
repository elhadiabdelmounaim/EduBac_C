from io import StringIO
from unittest.mock import Mock, patch

from django.core.management import call_command, CommandError
from django.test import SimpleTestCase, override_settings


@override_settings(
    DEFAULT_FROM_EMAIL='edubac@example.test',
    EMAIL_HOST_USER='edubac@example.test',
)
class CheckEmailCommandTests(SimpleTestCase):
    def setUp(self):
        self.connection = Mock()
        self.connection.open.return_value = True
        self.connection.send_messages.return_value = 1

    def test_connection_check_authenticates_without_sending_email(self):
        output = StringIO()
        with patch(
            'notifications.management.commands.check_email.get_connection',
            return_value=self.connection,
        ):
            call_command('check_email', stdout=output)

        self.connection.open.assert_called_once_with()
        self.connection.close.assert_called_once_with()
        self.connection.send_messages.assert_not_called()
        self.assertIn('authentification Gmail SMTP vérifiées', output.getvalue())
        self.assertIn('Aucun e-mail envoyé.', output.getvalue())

    def test_test_message_is_limited_to_the_supplied_recipient(self):
        output = StringIO()
        with patch(
            'notifications.management.commands.check_email.get_connection',
            return_value=self.connection,
        ):
            call_command(
                'check_email',
                '--send-test',
                'admin@example.test',
                stdout=output,
            )

        self.connection.send_messages.assert_called_once()
        message = self.connection.send_messages.call_args.args[0][0]
        self.assertEqual(message.to, ['admin@example.test'])
        self.assertEqual(message.cc, [])
        self.assertEqual(message.bcc, [])
        self.assertEqual(message.from_email, 'edubac@example.test')
        self.assertIn('accepté le message de test unique', output.getvalue())
        self.connection.close.assert_called_once_with()

    def test_invalid_test_address_does_not_open_smtp_connection(self):
        with (
            patch(
                'notifications.management.commands.check_email.get_connection',
                return_value=self.connection,
            ),
            self.assertRaises(CommandError),
        ):
            call_command('check_email', '--send-test', 'not-an-email')

        self.connection.open.assert_not_called()

    def test_authentication_failure_does_not_expose_server_error(self):
        self.connection.open.side_effect = RuntimeError('private SMTP response')
        with (
            patch(
                'notifications.management.commands.check_email.get_connection',
                return_value=self.connection,
            ),
            self.assertRaisesMessage(
                CommandError,
                'Connexion ou authentification Gmail SMTP échouée (RuntimeError).',
            ),
        ):
            call_command('check_email')

        self.connection.close.assert_not_called()
