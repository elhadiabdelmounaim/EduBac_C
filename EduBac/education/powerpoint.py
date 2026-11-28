"""Présentation PowerPoint d'une leçon (diapositives du mode « Présenter »), réservée aux
professeurs : media/lessons/<niveau>/<chapitre>/Presentation/<leçon>.pptx, jamais publique."""
from pathlib import Path

from django.conf import settings
from django.utils.text import slugify

from .media_library import chapter_relative

DOSSIER = 'Presentation'
TAILLE_MAX = 80 * 1024 * 1024


def dossier(lesson, owners=None):
    racine = Path(settings.MEDIA_ROOT).resolve()
    chemin = (racine / chapter_relative(lesson, owners) / DOSSIER).resolve()
    if not chemin.is_relative_to(racine):
        raise ValueError('Chemin de leçon invalide.')
    return chemin


def fichier(lesson):
    """Le .pptx de la leçon, ou None."""
    d = dossier(lesson)
    if not d.is_dir():
        return None
    candidats = sorted(p for p in d.iterdir() if p.suffix.lower() == '.pptx' and p.is_file() and not p.is_symlink())
    return candidats[0] if candidats else None


def nom_pour(lesson):
    return f'{lesson.order:02d}_{slugify(lesson.title)[:80] or "lecon"}.pptx'


def remplacer(lesson, source, owners=None):
    """Enregistre `source` (fichier téléversé ou chemin) comme présentation de la leçon,
    à la place de l'ancienne. Renvoie le chemin écrit."""
    d = dossier(lesson, owners)
    d.mkdir(parents=True, exist_ok=True)
    cible = d / nom_pour(lesson)
    temporaire = cible.with_suffix('.tmp')
    with open(temporaire, 'wb') as sortie:
        if isinstance(source, (str, Path)):
            with open(source, 'rb') as entree:
                while bloc := entree.read(1024 * 1024):
                    sortie.write(bloc)
        else:
            for bloc in source.chunks():
                sortie.write(bloc)
    for ancien in d.glob('*.pptx'):
        if ancien != cible:
            ancien.unlink()
    temporaire.replace(cible)
    return cible


def retirer(lesson):
    f = fichier(lesson)
    if f:
        f.unlink()
    return bool(f)
