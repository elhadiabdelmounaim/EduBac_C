"""Envoie à chaque professeur le rapport de la semaine de ses classes (notification + e-mail).
À planifier chaque dimanche soir, par exemple sur PythonAnywhere : tâche quotidienne à 19:00
`python manage.py rapport_hebdo --si-dimanche`."""
from django.core.management.base import BaseCommand
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from classrooms.models import Classroom
from classrooms.rapport import rapport_professeur, resume_texte


class Command(BaseCommand):
    help = 'Rapport hebdomadaire des classes pour chaque professeur.'

    def add_arguments(self, parser):
        parser.add_argument('--si-dimanche', action='store_true',
                            help='Ne rien faire les autres jours (tâche planifiée quotidienne).')

    def handle(self, *args, si_dimanche=False, **options):
        if si_dimanche and timezone.localdate().weekday() != 6:
            self.stdout.write('Pas dimanche : rien à envoyer.')
            return
        from notifications.services import notify_user
        envoyes = 0
        profs = User.objects.filter(pk__in=Classroom.objects.filter(is_active=True).values('teacher_id'), is_active=True)
        for prof in profs:
            rapport = rapport_professeur(prof)
            if not rapport['classes']:
                continue
            notify_user(
                user=prof,
                title='Rapport de la semaine',
                message=resume_texte(rapport),
                type='rapport',
                link=reverse('classrooms:rapport'),
                send_email=True,
                group_key=f'rapport:{timezone.localdate():%Y-%W}',
            )
            envoyes += 1
        self.stdout.write(self.style.SUCCESS(f'{envoyes} rapport(s) envoyé(s).'))
