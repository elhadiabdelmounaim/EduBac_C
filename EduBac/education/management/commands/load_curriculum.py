from pathlib import Path
from django.core.management.base import BaseCommand
from django.core.files import File
from django.conf import settings
from education.models import Course, Lesson
from education.curriculum import CURRICULUM

# code niveau → dossier media/lessons/
NIVEAU_FOLDER = {
    'tronc_commun': 'tc',
    '1ere_bac_sc': '1sc',
    '1ere_bac_sm': '1sm',
    '1ere_bac_lettres': '1let',
    '2eme_bac_svt': '2svt',
    '2eme_bac_pc': '2pc',
    '2eme_bac_lettres': '2let',
    '2eme_bac_sm': '2sm',
}


class Command(BaseCommand):
    help = 'Charge le programme de mathématiques EduBac (niveaux + leçons + contenus MD/PDF).'

    def handle(self, *args, **options):
        media_root = Path(settings.MEDIA_ROOT)
        lessons_root = media_root / 'lessons'

        Lesson.objects.all().delete()
        Course.objects.all().delete()

        total_lessons = 0
        with_content = 0

        for niveau in CURRICULUM:
            course, _ = Course.objects.update_or_create(
                name='Mathématiques',
                niveau=niveau['code'],
                defaults={
                    'description': f"Programme de mathématiques — {niveau['label']}",
                    'order': niveau['order'],
                },
            )
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
                    with_content += 1

                lesson, _ = Lesson.objects.update_or_create(
                    course=course,
                    order=i,
                    defaults={
                        'title': title,
                        'content': content,
                    },
                )

                # Lier le PDF s'il existe et n'est pas vide
                pdf_path = level_dir / f'{i:02d}.pdf'
                if pdf_path.is_file() and pdf_path.stat().st_size > 0:
                    rel = f'lessons/{folder}/{i:02d}.pdf'
                    with open(pdf_path, 'rb') as f:
                        lesson.pdf.save(rel, File(f), save=True)

                total_lessons += 1

            self.stdout.write(
                self.style.SUCCESS(
                    f"OK {niveau['label']} — {len(niveau['lessons'])} leçon(s)"
                )
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"\nProgramme chargé : {len(CURRICULUM)} niveaux, {total_lessons} leçons "
                f"({with_content} avec contenu Markdown)."
            )
        )
