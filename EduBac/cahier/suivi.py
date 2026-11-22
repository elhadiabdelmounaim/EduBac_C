"""Suivi du temps d'enseignement d'une leçon : durée prévue, réalisée et restante.

Le réalisé est toujours recalculé comme la somme des durées des séances enregistrées
(pour un enseignant, une classe et une leçon) : enregistrer de nouveau, modifier ou
supprimer une séance ne peut donc jamais déduire deux fois la même durée."""
from education.repartition import duree_prevue_minutes

DUREE_MAX = 8 * 60          # une séance ne dépasse pas une journée de cours


def duree(minutes):
    """95 → « 1 h 35 » ; 40 → « 40 min » ; 0 → « 0 min »."""
    minutes = int(minutes or 0)
    if minutes < 60:
        return f'{minutes} min'
    h, m = divmod(minutes, 60)
    return f'{h} h {m:02d}' if m else f'{h} h'


def minutes_realisees(seance):
    """Durée saisie pour la séance ; à défaut (séances anciennes), durée prévue des éléments traités."""
    if seance.duree_minutes is not None:
        return int(seance.duree_minutes)
    return sum(e.minutes for e in seance.elements.all())


def lire_duree(valeur):
    """Durée envoyée par un formulaire (minutes) → entier valide, None si absente, ValueError sinon."""
    if valeur is None or str(valeur).strip() == '':
        return None
    try:
        minutes = int(str(valeur).strip())
    except ValueError:
        raise ValueError('Durée invalide.')
    if not 1 <= minutes <= DUREE_MAX:
        raise ValueError(f'La durée doit être comprise entre 1 min et {duree(DUREE_MAX)}.')
    return minutes


def _pourcent(x):
    """58.333… → « 58,33 » (affichage français, deux décimales)."""
    return f'{x:.2f}'.replace('.', ',')


def bilan(prevu, realise):
    """Chiffres de la barre de progression. prevu peut être None (volume horaire inconnu)."""
    realise = max(0, int(realise or 0))
    data = {'realise': realise, 'realise_texte': duree(realise), 'prevu': prevu,
            'prevu_texte': duree(prevu) if prevu else '', 'connu': bool(prevu)}
    if prevu:
        restant = max(0, prevu - realise)
        fait = min(100.0, 100.0 * realise / prevu)
        data.update({
            'restant': restant, 'restant_texte': duree(restant),
            'depassement': max(0, realise - prevu), 'depassement_texte': duree(max(0, realise - prevu)),
            'pourcent': round(fait, 2), 'pourcent_texte': _pourcent(fait),
            'reste_pourcent': round(100 - fait, 2), 'reste_pourcent_texte': _pourcent(100 - fait),
            'largeur': f'{fait:.2f}',
        })
    return data


def bilan_lecon(seances, lesson):
    """Bilan d'une leçon à partir de ses séances (même enseignant, même classe)."""
    return bilan(duree_prevue_minutes(lesson), sum(minutes_realisees(s) for s in seances))
