"""Local lesson documents: scanned on each request, with no import step."""
from pathlib import Path
from django.conf import settings
from django.utils.text import slugify

LEVEL_FOLDERS = {
    'tronc_commun': 'tc', '1ere_bac_sc': '1sc', '1ere_bac_sm': '1sm',
    '1ere_bac_lettres': '1let', '2eme_bac_svt': '2svt', '2eme_bac_pc': '2pc',
    '2eme_bac_lettres': '2let', '2eme_bac_sm': '2sm',
}


def chapter_relative(lesson):
    from .models import Lesson
    level = LEVEL_FOLDERS.get(lesson.course.niveau, slugify(lesson.course.niveau))
    name = f"{lesson.order:02d}_{slugify(lesson.title)[:160] or 'lecon'}"
    # Match the organizer's ordering when multiple courses share a chapter name.
    peers = Lesson.objects.filter(
        course__niveau=lesson.course.niveau, order=lesson.order
    ).select_related('course').order_by('course__order', 'course_id', 'id')
    for peer in peers:
        if (slugify(peer.title)[:160] or 'lecon') == (slugify(lesson.title)[:160] or 'lecon'):
            if peer.pk != lesson.pk:
                name += f"_lecon-{lesson.pk}"
            break
    return Path('lessons') / level / name


def documents(lesson, kind):
    if kind not in ('Cours', 'Exercices', 'Sources_IA'):
        return []
    root = Path(settings.MEDIA_ROOT).resolve()
    folder = root / chapter_relative(lesson) / kind
    if not folder.resolve().is_relative_to(root) or not folder.is_dir():
        return []
    extension = '.txt' if kind == 'Sources_IA' else '.pdf'
    return sorted(
        (p for p in folder.iterdir()
         if p.suffix.lower() == extension and not p.is_symlink()
         and p.is_file() and p.resolve().is_relative_to(root)),
        key=lambda p: p.name.casefold(),
    )


def ai_source_text(lesson):
    """Read only UTF-8 text, bounded before decoding; preserve LaTeX literally."""
    limit = max(1, int(getattr(settings, 'QUIZ_LESSON_CONTEXT_CHARS', 5000)))
    chunks, remaining = [], limit * 4
    for path in documents(lesson, 'Sources_IA'):
        if remaining <= 0:
            break
        with path.open('r', encoding='utf-8-sig') as source:
            text = source.read(remaining).strip()
        if text:
            chunks.append(f"## Source : {path.name}\n{text}")
            remaining -= len(text)
    return '\n\n'.join(chunks)
