"""Prompt prêt à copier dans un assistant IA (ChatGPT, Claude…) pour écrire un quiz au format
d'import d'EduBac, à partir du plan et des règles du cours en ligne de la leçon.
Aucun appel d'API : le professeur colle la réponse (JSON) dans le formulaire d'import."""
import json

NATURES_REGLES = {'def', 'prop', 'thm', 'meth', 'rem', 'att'}
LONGUEUR_REGLE = 450
LONGUEUR_TOTALE = 7000
DIFFICULTES = {
    'mix': 'un mélange équilibré de questions faciles (easy), moyennes (medium) et difficiles (hard)',
    'easy': 'des questions faciles (easy) : application directe du cours',
    'medium': 'des questions moyennes (medium) : deux étapes de raisonnement',
    'hard': 'des questions difficiles (hard) : plusieurs étapes, pièges classiques',
}

EXEMPLE = {
    'quiz': {
        'title': 'Titre du quiz',
        'questions': [{
            'id': 'Q001',
            'type': 'multiple_choice',
            'statement': 'Énoncé avec des formules entre $...$, par exemple $f(x)=2x+3$.',
            'choices': [{'id': 'A', 'text': '5'}, {'id': 'B', 'text': '7'},
                        {'id': 'C', 'text': '8'}, {'id': 'D', 'text': '6'}],
            'correct_answer': 'B',
            'difficulty': 'easy',
            'points': 1,
            'explication': {
                'regle': 'La règle ou la propriété du cours utilisée.',
                'solution': 'Application pas à pas jusqu’à la bonne réponse. La bonne réponse est B.',
            },
        }],
    },
}


# Macros du cours en ligne (static/js/cours.js) → LaTeX standard, compris par tout assistant.
MACROS = [
    (r'\\vect\{([^{}]*)\}', r'\\overrightarrow{\1}'),
    (r'\\angv\{([^{}]*)\}\{([^{}]*)\}', r'(\\widehat{\1\\,;\2})'),
    (r'\\vu(?![a-zA-Z])', r'\\overrightarrow{u}'), (r'\\vv(?![a-zA-Z])', r'\\overrightarrow{v}'),
    (r'\\vw(?![a-zA-Z])', r'\\overrightarrow{w}'), (r'\\vn(?![a-zA-Z])', r'\\overrightarrow{n}'),
    (r'\\vi(?![a-zA-Z])', r'\\overrightarrow{i}'), (r'\\vj(?![a-zA-Z])', r'\\overrightarrow{j}'),
    (r'\\Rep(?![a-zA-Z])', r'\\left(O;\\overrightarrow{i},\\overrightarrow{j}\\right)'),
    (r'\\Cc(?![a-zA-Z])', r'(\\mathcal{C})'), (r'\\Dd(?![a-zA-Z])', r'(D)'),
    (r'\\R(?![a-zA-Z])', r'\\mathbb{R}'), (r'\\N(?![a-zA-Z])', r'\\mathbb{N}'),
]


def latex_standard(texte):
    import re
    for motif, remplacement in MACROS:
        texte = re.sub(motif, remplacement, texte)
    return texte


def _couper(texte, n):
    texte = ' '.join((texte or '').split())
    return texte if len(texte) <= n else texte[:n].rsplit(' ', 1)[0] + ' …'


def plan_et_regles(lesson):
    """(plan en lignes, règles du cours) depuis le cours en ligne, s'il existe."""
    from education.recherche_rapide import _paragraphes
    plan, regles, total = [], [], 0
    for p in _paragraphes(lesson, None):
        if p['genre'] == 'partie':
            plan.append(f"- {p['titre']}")
        elif p['genre'] == 'titre':
            plan.append(f"  - {p['titre']}")
        elif p['nature'] in NATURES_REGLES and p.get('source') and total < LONGUEUR_TOTALE:
            corps = p['source']
            if corps.startswith(p['titre']):
                corps = corps[len(p['titre']):].strip()
            regle = f"[{p['titre']}] {_couper(latex_standard(corps), LONGUEUR_REGLE)}"
            regles.append(regle)
            total += len(regle)
    return plan, regles


def construire_prompt(lesson, nombre=10, difficulte='mix'):
    nombre = max(3, min(int(nombre or 10), 40))
    difficulte = difficulte if difficulte in DIFFICULTES else 'mix'
    plan, regles = plan_et_regles(lesson)
    niveau = lesson.course.get_niveau_display()
    lignes = [
        f'Tu es professeur de mathématiques au lycée au Maroc (programme officiel, niveau : {niveau}).',
        f'Écris un quiz QCM de {nombre} questions sur la leçon « {lesson.title} », en français.',
        f'Difficulté : {DIFFICULTES[difficulte]}.',
        '',
        'Règles à respecter :',
        '- Chaque question a 4 choix (A, B, C, D) et une seule bonne réponse ; varie la lettre de la bonne réponse.',
        '- Les mauvais choix correspondent à des erreurs fréquentes des élèves.',
        '- Reste strictement dans le programme de la leçon, avec les notations du cours.',
        '- « explication.regle » : la règle ou la propriété DU COURS utilisée (reprends sa formulation ci-dessous).',
        '- « explication.solution » : la résolution pas à pas, terminée par « La bonne réponse est X. ».',
        '- Formules en LaTeX entre $...$ ; dans le JSON, double chaque antislash (\\\\frac, \\\\vec, \\\\times).',
        '- « difficulty » vaut easy, medium ou hard ; « points » vaut 1 (easy), 1.5 (medium) ou 2 (hard).',
        '- Réponds UNIQUEMENT par le JSON, sans texte avant ni après, exactement à ce format :',
        '',
        json.dumps(EXEMPLE, ensure_ascii=False, indent=2),
    ]
    if plan:
        lignes += ['', 'Plan de la leçon :'] + plan
    if regles:
        lignes += ['', 'Règles du cours (définitions, propriétés, méthodes) :'] + [f'- {r}' for r in regles]
    return '\n'.join(lignes)
