"""Déplace les pièces jointes du salon de classe de MEDIA_ROOT/chat vers le stockage privé.

Les noms de fichiers enregistrés en base ne changent pas : seul l'emplacement
physique change. Sans --apply, la commande se contente de lister.
"""
import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from chat.models import ChatMessage


class Command(BaseCommand):
    help = 'Déplace les anciennes pièces jointes du salon de classe hors de MEDIA_ROOT.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply', action='store_true',
            help='Effectuer le déplacement (par défaut : simulation).',
        )

    def handle(self, *args, apply=False, **options):
        media_root = Path(settings.MEDIA_ROOT).resolve()
        storage = ChatMessage._meta.get_field('attachment').storage
        private_root = Path(storage.location).resolve()
        moved = missing = already = 0
        for message in ChatMessage.objects.exclude(attachment='').exclude(attachment__isnull=True).iterator():
            name = message.attachment.name
            relative = Path(name)
            if relative.is_absolute() or '..' in relative.parts:
                self.stderr.write(f'Nom ignoré (chemin non sûr) : message {message.pk}')
                continue
            target = private_root / relative
            if target.exists():
                already += 1
                continue
            source = media_root / relative
            if not source.is_file() or source.is_symlink():
                missing += 1
                self.stderr.write(f'Fichier introuvable : message {message.pk} ({name})')
                continue
            moved += 1
            if apply:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                if target.stat().st_size == source.stat().st_size:
                    source.unlink()
                else:
                    target.unlink()
                    self.stderr.write(f'Copie incomplète, source conservée : message {message.pk}')
                    moved -= 1
        verb = 'déplacé(s)' if apply else 'à déplacer'
        self.stdout.write(self.style.SUCCESS(
            f'{moved} fichier(s) {verb}, {already} déjà en place, {missing} introuvable(s).'
        ))
        if not apply and moved:
            self.stdout.write('Relancez avec --apply pour effectuer le déplacement.')
