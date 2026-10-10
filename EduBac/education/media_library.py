"""Local lesson documents: scanned on each request, with no import step."""
from pathlib import Path
from django.conf import settings
from django.utils.text import slugify

LEVEL_FOLDERS = {
    'tronc_commun_lettres': 'TCL',
    'tronc_commun': 'TCS',
    'tronc_commun_technologie': 'TCT',
    '1ere_bac_sc': '1BAC_SE',
    '1ere_bac_lettres': '1BAC_L',
    '1ere_bac_sm': '1BAC_SM',
    '2eme_bac_svt': '2BAC_SVT',
    '2eme_bac_pc': '2BAC_PC',
    '2eme_bac_lettres': '2BAC_L',
    '2eme_bac_sm': '2BAC_SM',
}


def chapter_relative(lesson, owners=None):
    from .models import Lesson
    level = LEVEL_FOLDERS.get(lesson.course.niveau, slugify(lesson.course.niveau))
    name = f"{lesson.order:02d}_{slugify(lesson.title)[:160] or 'lecon'}"
    # Match the organizer's ordering when multiple courses share a chapter name.
    slug = slugify(lesson.title)[:160] or 'lecon'
    if owners is not None:
        owner = owners[(lesson.course.niveau, lesson.order, slug)]
    else:
        peers = Lesson.objects.filter(
            course__niveau=lesson.course.niveau, order=lesson.order
        ).select_related('course').order_by('course__order', 'course_id', 'id')
        owner = next((peer.pk for peer in peers
                      if (slugify(peer.title)[:160] or 'lecon') == slug), lesson.pk)
    if owner != lesson.pk:
        name += f"_lecon-{lesson.pk}"
    return Path('lessons') / level / name


def documents(lesson, kind, *, relative=None):
    if kind not in ('Cours', 'Exercices', 'Sources_IA'):
        return []
    root = Path(settings.MEDIA_ROOT).resolve()
    folder = root / (relative if relative is not None else chapter_relative(lesson)) / kind
    if not folder.resolve().is_relative_to(root) or not folder.is_dir():
        return []
    extension = '.txt' if kind == 'Sources_IA' else '.pdf'
    return sorted(
        (p for p in folder.iterdir()
         if p.suffix.lower() == extension and not p.is_symlink()
         and p.is_file() and p.resolve().is_relative_to(root)),
        key=lambda p: p.name.casefold(),
    )


def source_files_for_lessons(lessons):
    """Reuse the loaded catalogue; retain fresh disk scans and folder disambiguation."""
    lessons = list(lessons)
    owners = {}
    for lesson in sorted(lessons, key=lambda item: (item.course.order, item.course_id, item.pk)):
        key = (lesson.course.niveau, lesson.order, slugify(lesson.title)[:160] or 'lecon')
        owners.setdefault(key, lesson.pk)
    return {
        str(lesson.pk): [path.name for path in documents(
            lesson, 'Sources_IA', relative=chapter_relative(lesson, owners),
        )]
        for lesson in lessons
    }


def ai_source_text(lesson, source_file=None):
    """Read only UTF-8 text, bounded before decoding; preserve LaTeX literally."""
    limit = max(1, int(getattr(settings, 'QUIZ_LESSON_CONTEXT_CHARS', 5000)))
    chunks, remaining = [], limit * 4
    paths = documents(lesson, 'Sources_IA')
    if source_file:
        paths = [p for p in paths if p.name == source_file]
        if not paths:
            raise ValueError("Le fichier source sélectionné est introuvable pour cette leçon. Actualisez la page.")
    for path in paths:
        if remaining <= 0:
            break
        try:
            with path.open('r', encoding='utf-8-sig') as source:
                text = source.read(remaining).strip()
        except (OSError, UnicodeError) as exc:
            raise ValueError(
                f"Impossible de lire le fichier source « {path.name} ». Vérifiez son encodage UTF-8 et sa disponibilité."
            ) from exc
        if text:
            chunks.append(f"## Source : {path.name}\n{text}")
            remaining -= len(text)
    if source_file and not chunks:
        raise ValueError("Le fichier source sélectionné est vide. Choisissez un autre fichier.")
    return '\n\n'.join(chunks)
