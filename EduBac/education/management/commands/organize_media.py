"""Create curriculum folders from existing DB records without moving uploads."""
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils.text import slugify

from education.models import Lesson
from education.management.commands.load_curriculum import NIVEAU_FOLDER


class Command(BaseCommand):
    help = "Crée media/lessons/niveau/chapitre/{Cours,Exercices} sans modifier les fichiers existants."

    def handle(self, *args, **options):
        root = Path(settings.MEDIA_ROOT).resolve()
        lessons = list(Lesson.objects.select_related('course').order_by(
            'course__niveau', 'course__order', 'course_id', 'order', 'id'
        ))
        targets, seen, levels = [], set(), set()
        for lesson in lessons:
            level = NIVEAU_FOLDER.get(lesson.course.niveau, slugify(lesson.course.niveau))
            chapter = f"{lesson.order:02d}_{slugify(lesson.title)[:160] or 'lecon'}"
            relative = Path('lessons') / level / chapter
            if relative in seen:
                relative = relative.with_name(f"{chapter}_lecon-{lesson.pk}")
            seen.add(relative)
            levels.add(level)
            for kind in ('Cours', 'Exercices'):
                folder = root / relative / kind
                if not folder.resolve().is_relative_to(root):
                    raise CommandError(f"Chemin hors du dossier media : {folder}")
                targets.append(folder)
        created = 0
        for folder in targets:
            if not folder.exists():
                folder.mkdir(parents=True, exist_ok=True)
                created += 1
            # Git does not preserve empty directories. Never overwrite real files.
            marker = folder / '.gitkeep'
            if not any(folder.iterdir()):
                marker.touch(exist_ok=False)
        self.stdout.write(self.style.SUCCESS(
            f"{len(levels)} niveaux, {len(lessons)} leçons, "
            f"{created} sous-dossiers créés. Aucun fichier déplacé ou remplacé."
        ))
