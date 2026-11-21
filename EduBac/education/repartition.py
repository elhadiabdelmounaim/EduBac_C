"""Répartition horaire annuelle des leçons (référence : docs/references/…pdf).

Les heures sont lues dans education/data/repartition_horaire.json, une entrée par niveau
(dossier de media/lessons, ex. « 1BAC_SE ») et par numéro de leçon (« 04 »)."""
import json
from functools import lru_cache
from pathlib import Path

from .media_library import LEVEL_FOLDERS

FICHIER = Path(__file__).resolve().parent / 'data' / 'repartition_horaire.json'


@lru_cache(maxsize=1)
def _donnees():
    return json.loads(FICHIER.read_text(encoding='utf-8'))


def repartition_de_lecon(lesson):
    """{titre, semestre, semaines, heures, ponderation, annee} de la leçon, ou None."""
    niveau = LEVEL_FOLDERS.get(lesson.course.niveau)
    entree = (_donnees().get('niveaux', {}).get(niveau or '', {})
              .get('lecons', {}).get(f'{lesson.order:02d}'))
    if not entree:
        return None
    return dict(entree, annee=_donnees().get('annee', ''))
