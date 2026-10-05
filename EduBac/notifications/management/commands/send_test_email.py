from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from notifications.email_utils import send_notification_email


class Command(BaseCommand):
    help = 'Envoie un e-mail de test à un utilisateur (par e-mail ou username).'

    def add_arguments(self, parser):
        parser.add_argument('identifiant', type=str, help='E-mail ou username')

    def handle(self, *args, **options):
        User = get_user_model()
        ident = options['identifiant']
        user = User.objects.filter(email__iexact=ident).first() or User.objects.filter(username=ident).first()
        if not user:
            self.stderr.write(self.style.ERROR('Utilisateur introuvable.'))
            return
        ok = send_notification_email(
            recipient=user,
            title='Test EduBac — e-mail OK',
            message='Si vous lisez ce message, la configuration e-mail fonctionne.',
            link='/',
            type_code='system',
        )
        if ok:
            self.stdout.write(self.style.SUCCESS(f'E-mail envoyé à {user.email}'))
        else:
            self.stderr.write(self.style.ERROR('Échec envoi (voir logs / backend).'))
