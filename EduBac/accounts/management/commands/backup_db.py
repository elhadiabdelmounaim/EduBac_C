import sqlite3
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connections


class Command(BaseCommand):
    help = 'Crée une sauvegarde SQLite cohérente hors du dépôt.'

    def handle(self, *args, **options):
        db = settings.DATABASES['default']
        engine = db.get('ENGINE', '')
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        if 'sqlite' in engine:
            backup_dir = Path.home() / 'backups' / 'edubac'
            backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            backup_dir.chmod(0o700)
            dest = backup_dir / f'db_{stamp}.sqlite3'
            connection = connections['default']
            connection.ensure_connection()
            try:
                destination = sqlite3.connect(dest)
                try:
                    connection.connection.backup(destination)
                    integrity = destination.execute(
                        'PRAGMA integrity_check'
                    ).fetchone()[0]
                    if integrity != 'ok':
                        raise CommandError(
                            f'La sauvegarde SQLite est invalide : {integrity}'
                        )
                finally:
                    destination.close()
                dest.chmod(0o600)
            except Exception:
                dest.unlink(missing_ok=True)
                raise
            self.stdout.write(self.style.SUCCESS(f'Sauvegarde SQLite : {dest}'))
        else:
            self.stdout.write(
                self.style.WARNING(
                    'Base non-SQLite détectée : utilisez l’outil de sauvegarde '
                    'adapté (par exemple pg_dump pour PostgreSQL) et stockez le '
                    'fichier hors du dépôt, avec des permissions privées.'
                )
            )
