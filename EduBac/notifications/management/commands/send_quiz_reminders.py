from django.core.management.base import BaseCommand
from notifications.reminders import send_deadline_reminders


class Command(BaseCommand):
    help = 'Envoie les rappels de deadline des quiz (fenêtre 24 h).'

    def handle(self, *args, **options):
        n = send_deadline_reminders()
        self.stdout.write(self.style.SUCCESS(f'{n} rappel(s) créé(s).'))
