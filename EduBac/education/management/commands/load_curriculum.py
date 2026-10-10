from pathlib import Path
from django.core.management.base import BaseCommand
from django.conf import settings
from education.models import Course, Lesson
from education.curriculum import CURRICULUM
from education.media_library import LEVEL_FOLDERS

# code niveau → dossier media/lessons/
NIVEAU_FOLDER = LEVEL_FOLDERS


class Command(BaseCommand):
    help = 'Ajoute au besoin le programme EduBac sans écraser les contenus existants.'

    def handle(self, *args, **options):
        verbosity = options.get('verbosity', 1)
        media_root = Path(settings.MEDIA_ROOT)
        lessons_root = media_root / 'lessons'

        total_lessons = 0
        with_content = 0
        new_courses = 0
        new_lessons = 0

        for niveau in CURRICULUM:
            course, created = Course.objects.get_or_create(
                name='Mathématiques',
                niveau=niveau['code'],
                defaults={
                    'description': f"Programme de mathématiques — {niveau['label']}",
                    'order': niveau['order'],
                },
            )
            new_courses += int(created)
            folder = NIVEAU_FOLDER.get(niveau['code'], niveau['code'])
            level_dir = lessons_root / folder

            for i, title in enumerate(niveau['lessons'], start=1):
                content = (
                    f"## {title}\n\n"
                    f"Niveau : **{niveau['label']}**\n\n"
                    "Le support de cours sera ajouté ici (Markdown + LaTeX).\n"
                )
                # Chercher un fichier Markdown : 01.md, 01_*.md
                md_path = None
                if level_dir.is_dir():
                    candidates = [
                        level_dir / f'{i:02d}.md',
                        level_dir / f'{i:02d}_logique.md',
                    ]
                    candidates += sorted(level_dir.glob(f'{i:02d}_*.md'))
                    for c in candidates:
                        if c.is_file() and c.stat().st_size > 0:
                            md_path = c
                            break
                    # fallback: first lesson special name
                    if i == 1 and md_path is None:
                        for c in sorted(level_dir.glob('*logique*.md')):
                            if c.is_file() and c.stat().st_size > 0:
                                md_path = c
                                break

                if md_path:
                    content = md_path.read_text(encoding='utf-8')

                lesson, created = Lesson.objects.get_or_create(
                    course=course,
                    order=i,
                    defaults={
                        'title': title,
                        'content': content,
                    },
                )
                if created:
                    new_lessons += 1
                    if md_path:
                        with_content += 1

                # Lier le PDF s'il existe et n'est pas vide
                pdf_path = level_dir / f'{i:02d}.pdf'
                if (
                    not lesson.pdf
                    and pdf_path.is_file()
                    and pdf_path.stat().st_size > 0
                ):
                    rel = f'lessons/{folder}/{i:02d}.pdf'
                    # Link the existing PDF in place; FileField.save would copy it.
                    lesson.pdf.name = rel
                    lesson.save(update_fields=['pdf'])

                total_lessons += 1

            if verbosity >= 1:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"OK {niveau['label']} — {len(niveau['lessons'])} leçon(s)"
                    )
                )

        if verbosity >= 1:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\nCatalogue prêt : {len(CURRICULUM)} niveaux, {total_lessons} leçons "
                    f"({new_courses} niveaux et {new_lessons} leçons ajoutés ; "
                    f"{with_content} avec contenu Markdown)."
                )
            )
