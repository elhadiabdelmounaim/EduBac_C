from django.core.management.base import BaseCommand

from notifications.reminders import send_deadline_reminders, send_missed_deadline_alerts


class Command(BaseCommand):
    help = (
        'Rappels de date limite aux élèves (48 h avant) et alertes aux professeurs '
        'pour les quiz non faits. À planifier toutes les heures.'
    )

    def handle(self, *args, **options):
        reminders = send_deadline_reminders()
        missed = send_missed_deadline_alerts()
        self.stdout.write(self.style.SUCCESS(
            f'{reminders} rappel(s) élève, {missed} alerte(s) professeur.'
        ))
