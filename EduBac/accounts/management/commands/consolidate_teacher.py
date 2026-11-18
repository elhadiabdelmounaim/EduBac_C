"""EduBac fonctionne avec un seul enseignant : l'administrateur de la plateforme.

Ce script transfère à l'administrateur tout ce que possèdent les anciens comptes
« enseignant » (classes, quiz, tableaux, consultations) puis désactive ces
comptes. Rien n'est supprimé : les messages déjà envoyés gardent leur auteur.

    python manage.py backup_db
    python manage.py consolidate_teacher            # simulation (aucune écriture)
    python manage.py consolidate_teacher --apply
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import User
from chat.models import PrivateConversation
from classrooms.models import Classroom
from quizzes.models import Quiz, QuizGenerationRun
from whiteboard.models import WhiteboardBoard, WhiteboardShare

# (libellé, modèle, champ propriétaire)
OWNED = [
    ('classes', Classroom, 'teacher'),
    ('quiz', Quiz, 'created_by'),
    ('générations de quiz', QuizGenerationRun, 'owner'),
    ('tableaux', WhiteboardBoard, 'created_by'),
    ('partages de tableau', WhiteboardShare, 'teacher'),
]


class Command(BaseCommand):
    help = "Transfère à l'administrateur le contenu des anciens comptes enseignant et les désactive."

    def add_arguments(self, parser):
        parser.add_argument('--admin', help="Nom d'utilisateur de l'administrateur (par défaut : le premier superutilisateur actif).")
        parser.add_argument('--apply', action='store_true', help='Écrire réellement (sinon simulation).')

    def handle(self, *args, **options):
        admin = self._admin(options.get('admin'))
        teachers = list(
            User.objects.filter(role='teacher', is_staff=False, is_superuser=False)
            .exclude(pk=admin.pk).order_by('username')
        )
        apply = options['apply']
        self.stdout.write(f'Administrateur enseignant : {admin.username}')
        if not teachers:
            self.stdout.write(self.style.SUCCESS('Aucun autre compte enseignant : rien à faire.'))
            return
        self.stdout.write('Comptes enseignant à désactiver : ' + ', '.join(t.username for t in teachers))

        with transaction.atomic():
            for label, model, field in OWNED:
                qs = model.objects.filter(**{f'{field}__in': teachers})
                count = qs.count()
                if apply and count:
                    qs.update(**{field: admin})
                self.stdout.write(f'  {label} : {count}')
            moved, kept = self._consultations(teachers, admin, apply)
            self.stdout.write(f'  consultations : {moved}' + (f' ({kept} déjà existantes chez l’administrateur, conservées à part)' if kept else ''))
            if apply:
                User.objects.filter(pk__in=[t.pk for t in teachers]).update(is_active=False)

        if apply:
            self.stdout.write(self.style.SUCCESS(f'{len(teachers)} compte(s) désactivé(s). Transfert terminé.'))
        else:
            self.stdout.write(self.style.WARNING('Simulation : rien n’a été modifié. Relancez avec --apply.'))

    def _admin(self, username):
        qs = User.objects.filter(is_active=True).filter(is_superuser=True) | User.objects.filter(is_active=True, is_staff=True)
        if username:
            admin = qs.filter(username=username).first()
            if not admin:
                raise CommandError(f'« {username} » n’est pas un administrateur actif.')
            return admin
        admin = (
            User.objects.filter(is_active=True, is_superuser=True).order_by('pk').first()
            or User.objects.filter(is_active=True, is_staff=True).order_by('pk').first()
        )
        if not admin:
            raise CommandError('Aucun administrateur actif. Créez-en un avec createsuperuser.')
        return admin

    def _consultations(self, teachers, admin, apply):
        """Une consultation par (classe, élève, enseignant) : on évite les doublons."""
        moved = kept = 0
        for conversation in PrivateConversation.objects.filter(teacher__in=teachers):
            duplicate = PrivateConversation.objects.filter(
                classroom_id=conversation.classroom_id,
                student_id=conversation.student_id,
                teacher=admin,
            ).exists()
            if duplicate:
                kept += 1
                continue
            moved += 1
            if apply:
                conversation.teacher = admin
                conversation.save(update_fields=['teacher'])
        return moved, kept
