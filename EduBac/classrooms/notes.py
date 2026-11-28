"""Carnet de notes : valeurs de chaque colonne (saisie, devoir, quiz), moyennes pondérées,
suggestions de colonnes à ajouter, export Excel. Toutes les notes sont sur 20."""
from decimal import ROUND_HALF_UP, Decimal

from .models import ClassroomMember, ColonneNote, NoteSaisie

VINGT = Decimal(20)


def arrondi(valeur, chiffres='0.01'):
    return None if valeur is None else Decimal(valeur).quantize(Decimal(chiffres), rounding=ROUND_HALF_UP)


def texte(valeur):
    """Decimal('15.50') → « 15,5 » ; None → « »."""
    if valeur is None:
        return ''
    return f'{Decimal(valeur).normalize():f}'.replace('.', ',')


def eleves_de(classe):
    return [m.user for m in ClassroomMember.objects.filter(classroom=classe, user__role='student')
            .select_related('user').order_by('user__last_name', 'user__first_name', 'user__username')]


def valeurs(colonnes, eleves):
    """{(colonne_id, eleve_id): Decimal sur 20}, en une requête par source."""
    from devoirs.models import RenduDevoir
    from quizzes.models import Attempt
    ids = [e.pk for e in eleves]
    resultat = {}
    manuelles = [c for c in colonnes if c.source == ColonneNote.MANUEL]
    for n in NoteSaisie.objects.filter(colonne__in=manuelles, eleve_id__in=ids, note__isnull=False):
        resultat[(n.colonne_id, n.eleve_id)] = n.note
    par_devoir = {c.devoir_id: c for c in colonnes if c.source == ColonneNote.DEVOIR and c.devoir_id}
    for r in RenduDevoir.objects.filter(devoir_id__in=par_devoir, eleve_id__in=ids, note__isnull=False):
        resultat[(par_devoir[r.devoir_id].pk, r.eleve_id)] = r.note
    par_quiz = {c.quiz_id: c for c in colonnes if c.source == ColonneNote.QUIZ and c.quiz_id}
    # Dernière tentative rendue de chaque élève (score % → /20).
    for t in (Attempt.objects.filter(quiz_id__in=par_quiz, student_id__in=ids, submitted_at__isnull=False, score__isnull=False)
              .order_by('submitted_at', 'pk')):
        resultat[(par_quiz[t.quiz_id].pk, t.student_id)] = arrondi(Decimal(str(t.score)) * VINGT / 100)
    return resultat


def moyenne(notes):
    """notes : [(Decimal, coefficient)] → moyenne pondérée ou None."""
    total_coef = sum(c for _, c in notes)
    if not total_coef:
        return None
    return arrondi(sum(n * c for n, c in notes) / total_coef)


def tableau(classe, *, pour_eleve=None):
    colonnes = list(classe.colonnes_notes.select_related('devoir', 'quiz'))
    if pour_eleve is not None:
        colonnes = [c for c in colonnes if c.visible_eleves]
    eleves = [pour_eleve] if pour_eleve is not None else eleves_de(classe)
    v = valeurs(colonnes, eleves)
    lignes = []
    for e in eleves:
        cellules = [{'colonne': c, 'note': v.get((c.pk, e.pk)), 'texte': texte(v.get((c.pk, e.pk)))} for c in colonnes]
        moy = moyenne([(x['note'], x['colonne'].coefficient) for x in cellules
                       if x['note'] is not None and x['colonne'].dans_moyenne])
        lignes.append({'eleve': e, 'cellules': cellules, 'moyenne': moy, 'moyenne_texte': texte(moy)})
    for i, c in enumerate(colonnes):
        notes = [l['cellules'][i]['note'] for l in lignes if l['cellules'][i]['note'] is not None]
        c.moyenne_classe = arrondi(sum(notes) / len(notes)) if notes else None
        c.moyenne_texte = texte(c.moyenne_classe)
        c.coef_texte = texte(c.coefficient)
        c.nb_notes = len(notes)
    moyennes = [l['moyenne'] for l in lignes if l['moyenne'] is not None]
    moyenne_classe = arrondi(sum(moyennes) / len(moyennes)) if moyennes else None
    return {
        'colonnes': colonnes, 'lignes': lignes,
        'moyenne_classe': moyenne_classe, 'moyenne_classe_texte': texte(moyenne_classe),
    }


def suggestions(classe):
    """Devoirs (rendu en ligne) et quiz de la classe qui n'ont pas encore de colonne."""
    from devoirs.models import Devoir
    from quizzes.models import Quiz, QuizAssignment
    deja_devoirs = set(classe.colonnes_notes.filter(source=ColonneNote.DEVOIR).values_list('devoir_id', flat=True))
    deja_quiz = set(classe.colonnes_notes.filter(source=ColonneNote.QUIZ).values_list('quiz_id', flat=True))
    devoirs = [d for d in Devoir.objects.filter(classes=classe, rendu_en_ligne=True).order_by('-cree_le')
               if d.pk not in deja_devoirs]
    eleves = ClassroomMember.objects.filter(classroom=classe).values('user_id')
    quiz_ids = set(QuizAssignment.objects.filter(student_id__in=eleves).values_list('quiz_id', flat=True))
    quiz_ids |= set(Quiz.objects.filter(classroom=classe).values_list('pk', flat=True))
    quiz = [q for q in Quiz.objects.filter(pk__in=quiz_ids, status='published').order_by('-created_at')
            if q.pk not in deja_quiz]
    return devoirs, quiz


def classeur_excel(classe):
    """Classeur Excel (openpyxl, déjà utilisé pour les résultats) du carnet de la classe."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    t = tableau(classe)
    wb = Workbook()
    ws = wb.active
    ws.title = (classe.name or 'Classe')[:31]
    entete = ['Élève'] + [f'{c.titre} (coef {texte(c.coefficient)})' for c in t['colonnes']] + ['Moyenne /20']
    ws.append(entete)
    for cellule in ws[1]:
        cellule.font = Font(bold=True, color='FFFFFF')
        cellule.fill = PatternFill('solid', fgColor='1D4FA3')
        cellule.alignment = Alignment(wrap_text=True, vertical='center')
    for l in t['lignes']:
        e = l['eleve']
        ws.append([e.get_full_name() or e.username]
                  + [float(x['note']) if x['note'] is not None else None for x in l['cellules']]
                  + [float(l['moyenne']) if l['moyenne'] is not None else None])
    ws.append(['Moyenne de la classe'] + [float(c.moyenne_classe) if c.moyenne_classe is not None else None
                                          for c in t['colonnes']]
              + [float(t['moyenne_classe']) if t['moyenne_classe'] is not None else None])
    for cellule in ws[ws.max_row]:
        cellule.font = Font(bold=True)
    ws.column_dimensions['A'].width = 28
    for i in range(2, len(entete) + 1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = 16
    ws.freeze_panes = 'B2'
    return wb
