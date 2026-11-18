"""Envoie le résumé quotidien des notifications par e-mail.

À planifier une fois par jour (ex. 18 h). Seules les notifications marquées
« résumé » et encore non lues sont envoyées ; celles déjà lues dans EduBac
n'encombrent pas la boîte mail.
"""
from collections import defaultdict

from django.core.management.base import BaseCommand

from notifications.email_utils import send_digest_email
from notifications.models import Notification


class Command(BaseCommand):
    help = 'Envoie à chaque utilisateur un e-mail récapitulant ses notifications en attente.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Afficher sans envoyer.')

    def handle(self, *args, dry_run=False, **options):
        pending = (
            Notification.objects.filter(email_status=Notification.EMAIL_DIGEST)
            .select_related('recipient')
            .order_by('recipient_id', '-updated_at')
        )
        by_user = defaultdict(list)
        for notification in pending:
            by_user[notification.recipient].append(notification)

        sent = skipped = 0
        for recipient, notifications in by_user.items():
            unread = [n for n in notifications if not n.is_read]
            ids = [n.pk for n in notifications]
            if dry_run:
                self.stdout.write(f'{recipient.username} : {len(unread)} notification(s)')
                continue
            if unread and send_digest_email(recipient, unread[:50]):
                sent += 1
                Notification.objects.filter(pk__in=ids).update(email_status=Notification.EMAIL_SENT)
            else:
                skipped += 1
                # Déjà lues ou pas d'adresse : rien à envoyer, on ne les garde pas en attente.
                if not unread or not (recipient.email and '@' in recipient.email):
                    Notification.objects.filter(pk__in=ids).update(email_status=Notification.EMAIL_NONE)
        if not dry_run:
            self.stdout.write(self.style.SUCCESS(f'{sent} résumé(s) envoyé(s), {skipped} ignoré(s).'))
