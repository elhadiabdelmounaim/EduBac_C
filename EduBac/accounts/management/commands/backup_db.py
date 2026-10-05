from django.core.management.base import BaseCommand
from django.conf import settings
from pathlib import Path
import shutil
from datetime import datetime


class Command(BaseCommand):
    help = 'Sauvegarde simple de la base SQLite (ou indique PostgreSQL).'

    def handle(self, *args, **options):
        db = settings.DATABASES['default']
        engine = db.get('ENGINE', '')
        backup_dir = Path(settings.BASE_DIR) / 'backups'
        backup_dir.mkdir(exist_ok=True)
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        if 'sqlite' in engine:
            src = Path(db['NAME'])
            dest = backup_dir / f'db_{stamp}.sqlite3'
            shutil.copy2(src, dest)
            self.stdout.write(self.style.SUCCESS(f'Sauvegarde SQLite : {dest}'))
        else:
            self.stdout.write(
                self.style.WARNING(
                    'PostgreSQL détecté : utilisez pg_dump. Exemple :\n'
                    f'  pg_dump {db.get("NAME")} > backups/db_{stamp}.sql'
                )
            )
