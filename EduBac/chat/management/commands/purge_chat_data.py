"""Politique de conservation des données de messagerie (loi 09-08).

- Supprime les fichiers joints plus anciens que --attachments-days (365 j par défaut).
  Le message reste, avec la mention du fichier retiré.
- Efface définitivement les messages supprimés depuis plus de --deleted-days (30 j).
- Efface les signalements traités depuis plus de --reports-days (365 j).

Sans --apply, la commande affiche seulement ce qui serait supprimé.
À planifier par exemple chaque nuit (cron) une fois les durées validées.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from chat.models import ChatMessage, ChatReport, DirectMessage, PrivateMessage

MODELS = (ChatMessage, PrivateMessage, DirectMessage)


class Command(BaseCommand):
    help = 'Applique la durée de conservation des messages et pièces jointes.'

    def add_arguments(self, parser):
        parser.add_argument('--attachments-days', type=int, default=365)
        parser.add_argument('--deleted-days', type=int, default=30)
        parser.add_argument('--reports-days', type=int, default=365)
        parser.add_argument('--apply', action='store_true', help='Effectuer la suppression.')

    def handle(self, *args, attachments_days, deleted_days, reports_days, apply=False, **options):
        for value in (attachments_days, deleted_days, reports_days):
            if value < 1:
                self.stderr.write('Les durées doivent être d’au moins 1 jour.')
                return
        now = timezone.now()
        files = purged = reports = 0

        for model in MODELS:
            old = model.objects.filter(
                created_at__lt=now - timedelta(days=attachments_days),
            ).exclude(attachment='').exclude(attachment__isnull=True)
            for message in old.iterator():
                files += 1
                if apply:
                    message.attachment.delete(save=False)
                    message.attachment = None
                    note = '[fichier retiré après la durée de conservation]'
                    message.body = f'{message.body}\n{note}'.strip() if message.body else note
                    message.save(update_fields=['attachment', 'body'])

            deleted = model.objects.filter(deleted_at__lt=now - timedelta(days=deleted_days))
            count = deleted.count()
            purged += count
            if apply and count:
                for message in deleted.exclude(attachment='').exclude(attachment__isnull=True).iterator():
                    message.attachment.delete(save=False)
                deleted.delete()

        handled = ChatReport.objects.exclude(status=ChatReport.STATUS_OPEN).filter(
            handled_at__lt=now - timedelta(days=reports_days),
        )
        reports = handled.count()
        if apply and reports:
            handled.delete()

        prefix = '' if apply else '[simulation] '
        self.stdout.write(self.style.SUCCESS(
            f'{prefix}{files} fichier(s) joint(s) retiré(s), {purged} message(s) supprimé(s) '
            f'effacé(s), {reports} signalement(s) archivé(s) effacé(s).'
        ))
        if not apply:
            self.stdout.write('Relancez avec --apply pour appliquer.')
