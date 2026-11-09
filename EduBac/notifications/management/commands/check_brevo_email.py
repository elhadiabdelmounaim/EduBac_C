"""Check Brevo API access and optionally send one real test email."""

from email.utils import parseaddr

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.core.management.base import BaseCommand, CommandError

from config.email_backend import BrevoAPIEmailBackend, BrevoAPIError


class Command(BaseCommand):
    help = (
        'Vérifie l’accès à l’API Brevo; --send-test envoie un e-mail '
        'à DEFAULT_FROM_EMAIL.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--send-test',
            action='store_true',
            help='Envoie un message réel à l’adresse expéditrice vérifiée.',
        )

    def handle(self, *args, **options):
        backend = BrevoAPIEmailBackend()
        try:
            backend.test_connection()
        except BrevoAPIError as exc:
            raise CommandError(str(exc)) from None

        self.stdout.write(self.style.SUCCESS('Connexion à l’API Brevo vérifiée.'))
        if not options['send_test']:
            self.stdout.write(
                'Aucun e-mail envoyé. Ajoute --send-test pour envoyer un test.'
            )
            return

        recipient = parseaddr(settings.DEFAULT_FROM_EMAIL)[1]
        if not recipient:
            raise CommandError(
                'DEFAULT_FROM_EMAIL doit contenir une adresse vérifiée dans Brevo.'
            )

        try:
            message = EmailMultiAlternatives(
                subject='Test EduBac — API Brevo',
                body=(
                    'Ce message confirme le test d’envoi EduBac via '
                    'l’API Brevo.'
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[recipient],
                connection=backend,
            )
            sent = message.send(fail_silently=False)
        except BrevoAPIError as exc:
            raise CommandError(str(exc)) from None

        if sent != 1:
            raise CommandError('Brevo n’a pas accepté le message de test.')
        self.stdout.write(
            self.style.SUCCESS('E-mail de test accepté par Brevo.')
        )
