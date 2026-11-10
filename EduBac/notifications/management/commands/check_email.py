"""Verify Gmail SMTP authentication and optionally send one test email."""

import logging

from django.conf import settings
from django.core.mail import EmailMessage, get_connection
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.core.exceptions import ValidationError

from config.email_diagnostics import log_email_exception


logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = (
        'Vérifie la connexion et l’authentification Gmail SMTP; '
        '--send-test ADRESSE envoie un seul message à cette adresse.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--send-test',
            metavar='ADRESSE',
            help='Envoie un message réel à une seule adresse de test.',
        )

    def handle(self, *args, **options):
        recipient = options['send_test']
        if recipient:
            try:
                validate_email(recipient)
            except ValidationError:
                raise CommandError('L’adresse de test est invalide.') from None
        if not settings.EMAIL_HOST_USER or not settings.EMAIL_HOST_PASSWORD:
            raise CommandError(
                'EMAIL_HOST_USER et EMAIL_HOST_PASSWORD doivent être configurés.'
            )
        for setting_name, sender in (
            ('EMAIL_HOST_USER', settings.EMAIL_HOST_USER),
            ('DEFAULT_FROM_EMAIL', settings.DEFAULT_FROM_EMAIL),
        ):
            try:
                validate_email(sender)
            except ValidationError:
                raise CommandError(f'{setting_name} doit contenir une adresse valide.') from None

        connection = get_connection(fail_silently=False)
        try:
            connection.open()
        except Exception as exc:
            log_email_exception(
                logger,
                event='smtp_test',
                stage='connection_authentication',
                exc=exc,
            )
            raise CommandError(
                'Connexion ou authentification Gmail SMTP échouée '
                f'({type(exc).__name__}).'
            ) from None

        self.stdout.write(
            self.style.SUCCESS('Connexion et authentification Gmail SMTP vérifiées.')
        )
        if not recipient:
            self.stdout.write('Aucun e-mail envoyé.')
            try:
                connection.close()
            except Exception:
                pass
            return

        try:
            message = EmailMessage(
                subject='Test EduBac — Gmail SMTP',
                body='Le serveur Gmail SMTP a accepté ce message de test EduBac.',
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[recipient],
                connection=connection,
            )
            sent = message.send(fail_silently=False)
        except Exception as exc:
            log_email_exception(
                logger,
                event='smtp_test',
                stage='send_test',
                exc=exc,
            )
            raise CommandError(
                f'Échec de l’envoi SMTP ({type(exc).__name__}).'
            ) from None
        finally:
            try:
                connection.close()
            except Exception:
                pass

        if sent != 1:
            raise CommandError('Le serveur SMTP n’a pas accepté le message de test.')
        self.stdout.write(
            self.style.SUCCESS(
                'Le serveur Gmail SMTP a accepté le message de test unique.'
            )
        )
