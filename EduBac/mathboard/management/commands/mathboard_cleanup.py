"""Entretien du tableau mathématique (à lancer chaque jour, par exemple en
tâche planifiée PythonAnywhere : `python manage.py mathboard_cleanup`).

1. Journal d'opérations : ne garde que le récent (voir prune_operations).
2. Images incluses dans la base (data:…) : déplacées dans media/mathboard/
   (servies par /tableau-maths/<id>/images/…, avec contrôle d'accès).
3. Fichiers images qui ne servent plus à aucune page ni version : supprimés.
4. Présences périmées : supprimées.
"""
import base64
import binascii
import json
import re
import time
from datetime import timedelta

from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand
from django.utils import timezone

from mathboard.images import referenced_names, save_image
from mathboard.models import WhiteboardDocument, WhiteboardPage, WhiteboardSession, WhiteboardSnapshot
from mathboard.operations import prune_operations

DATA_URL = re.compile(r'^data:image/(png|jpeg|webp);base64,(.+)$', re.S)
EXTENSIONS = {'png': 'png', 'jpeg': 'jpg', 'webp': 'webp'}
ORPHAN_GRACE = 24 * 3600  # un fichier tout juste envoyé n'est peut-être pas encore utilisé


def _move_images(objects, document_id, dry_run):
    """Remplace les images data:… d'un dict d'objets par des fichiers. Renvoie le nombre."""
    moved = 0
    for obj in objects.values():
        if not isinstance(obj, dict) or obj.get('type') != 'image':
            continue
        match = DATA_URL.match(str(obj.get('src', '')))
        if not match:
            continue
        try:
            data = base64.b64decode(match.group(2))
        except (binascii.Error, ValueError):
            continue
        moved += 1
        if not dry_run:
            obj['src'] = save_image(document_id, data, EXTENSIONS[match.group(1)])
    return moved


class Command(BaseCommand):
    help = 'Entretien du tableau mathématique : journal, images, présences.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Affiche ce qui serait fait, sans rien changer.')

    def handle(self, *args, dry_run=False, **options):
        pruned = 0
        for document in WhiteboardDocument.objects.only('pk', 'revision').iterator():
            if not dry_run:
                pruned += prune_operations(document)

        moved = 0
        for page in WhiteboardPage.objects.iterator():
            if 'data:image' not in json.dumps(page.content):
                continue
            count = _move_images(page.content, page.document_id, dry_run)
            if count and not dry_run:
                WhiteboardPage.objects.filter(pk=page.pk).update(content=page.content)
            moved += count
        for snapshot in WhiteboardSnapshot.objects.iterator():
            if 'data:image' not in json.dumps(snapshot.data):
                continue
            count = sum(_move_images(p.get('objects') or {}, snapshot.document_id, dry_run)
                        for p in snapshot.data.get('pages') or [])
            if count and not dry_run:
                WhiteboardSnapshot.objects.filter(pk=snapshot.pk).update(data=snapshot.data)
            moved += count

        orphans = self._orphans(dry_run)
        stale = WhiteboardSession.objects.filter(last_seen__lt=timezone.now() - timedelta(days=1))
        sessions = stale.count()
        if not dry_run:
            stale.delete()
        prefix = '[simulation] ' if dry_run else ''
        self.stdout.write(self.style.SUCCESS(
            f'{prefix}Opérations supprimées : {pruned} · images déplacées vers media/ : {moved} · '
            f'fichiers inutilisés supprimés : {orphans} · présences périmées : {sessions}'))

    def _orphans(self, dry_run):
        used = set()
        for content in WhiteboardPage.objects.values_list('content', flat=True).iterator():
            used.update(referenced_names(json.dumps(content)))
        for data in WhiteboardSnapshot.objects.values_list('data', flat=True).iterator():
            used.update(referenced_names(json.dumps(data)))
        removed = 0
        try:
            folders = default_storage.listdir('mathboard')[0]
        except (FileNotFoundError, NotImplementedError, OSError):
            return 0
        for folder in folders:
            for filename in default_storage.listdir(f'mathboard/{folder}')[1]:
                name = f'mathboard/{folder}/{filename}'
                if name in used:
                    continue
                try:
                    age = time.time() - default_storage.get_modified_time(name).timestamp()
                except (NotImplementedError, OSError):
                    continue
                if age < ORPHAN_GRACE:
                    continue
                removed += 1
                if not dry_run:
                    default_storage.delete(name)
        return removed
