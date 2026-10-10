"""Rename resource level folders without copying files or changing curriculum IDs."""
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import FileField


# Legacy names belong only to this one-time compatibility command.
RENAMES = {
    'tc': 'TCS', '1sc': '1BAC_SE', '1let': '1BAC_L', '1sm': '1BAC_SM',
    '2svt': '2BAC_SVT', '2pc': '2BAC_PC', '2let': '2BAC_L', '2sm': '2BAC_SM',
}


class Command(BaseCommand):
    help = "Normalise les dossiers des niveaux sans perte de fichiers ni changement de schéma."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help="Affiche les changements sans modifier les fichiers ou les données.")

    def handle(self, *args, **options):
        root = Path(settings.MEDIA_ROOT).resolve()
        base = root / 'lessons'
        if base.is_symlink():
            raise CommandError("Le dossier lessons ne doit pas être un lien symbolique.")
        moves, updates = [], []
        for old, new in RENAMES.items():
            source, target = base / old, base / new
            if source.is_symlink() or target.is_symlink():
                raise CommandError(f"Lien symbolique refusé : {old} → {new}")
            if source.exists():
                if not source.is_dir() or target.exists():
                    raise CommandError(
                        f"Conflit {old} → {new} : aucun fichier n'a été déplacé. "
                        "La destination doit être absente ; aucune fusion automatique."
                    )
                moves.append((source, target))
        # Preserve linked PDFs and any other FileField referring to the moved tree.
        # IDs, level codes and all non-file fields remain unchanged.
        for model in apps.get_models():
            for field in model._meta.fields:
                if not isinstance(field, FileField):
                    continue
                for old, new in RENAMES.items():
                    prefix = f'lessons/{old}/'
                    rows = model.objects.filter(**{f'{field.name}__startswith': prefix})
                    for pk, value in rows.values_list('pk', field.name):
                        replacement = f'lessons/{new}/' + value[len(prefix):]
                        source, target = root / value, root / replacement
                        if (not source.resolve().is_relative_to(root)
                                or not target.resolve().is_relative_to(root)):
                            raise CommandError("Une référence de fichier sort du dossier media.")
                        if not source.is_file() and not target.is_file():
                            raise CommandError(
                                f"Fichier lié introuvable : {model._meta.label}.{field.name} "
                                f"(id={pk}). Aucune modification appliquée."
                            )
                        updates.append((model, field.name, pk, value, replacement))
        for source, target in moves:
            self.stdout.write(f"{source.name} → {target.name}")
        if options['dry_run']:
            self.stdout.write(
                f"Simulation : {len(moves)} dossiers, {len(updates)} références à mettre à jour."
            )
            return
        moved = []
        try:
            with transaction.atomic():
                for source, target in moves:
                    source.rename(target)
                    moved.append((source, target))
                for model, name, pk, old, new in updates:
                    changed = model.objects.filter(pk=pk, **{name: old}).update(**{name: new})
                    if changed != 1:
                        raise CommandError("Une référence a changé pendant le renommage.")
        except Exception:
            # Restore renamed directories when the matching DB transaction fails.
            # No file contents are copied, removed, or overwritten.
            for source, target in reversed(moved):
                target.rename(source)
            raise
        self.stdout.write(self.style.SUCCESS(
            f"{len(moved)} dossiers renommés, {len(updates)} références mises à jour. "
            "Aucun fichier supprimé, copié ou remplacé."
        ))
