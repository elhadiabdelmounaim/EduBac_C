"""
Templates de prompts pour l'assistant IA EduBac.
"""

DIFFICULTY_GUIDE = {
    "facile": (
        "DIFFICULTÉ FACILE : application directe d'une notion, calcul en 1 ou 2 étapes, "
        "formules utilisées telles quelles, distracteurs évidents. Pas de piège, "
        "de cas particulier ni de démonstration."
    ),
    "moyen": (
        "DIFFICULTÉ MOYENNE : 2 ou 3 étapes, une ou deux notions de la leçon, "
        "calculs habituels du programme, distracteurs plausibles. "
        "Pas de démonstration longue ni d'exercice de bac complet."
    ),
    "difficile": (
        "DIFFICULTÉ DIFFICILE : 3 étapes ou plus, synthèse des notions présentes "
        "dans le contenu, pièges du bac, distracteurs proches, justification possible. "
        "Niveau examen, énoncé clair, strictement sur le contenu fourni."
    ),
}


def difficulty_instructions(difficulty: str) -> str:
    key = (difficulty or "moyen").strip().lower()
    if key not in DIFFICULTY_GUIDE:
        key = "moyen"
    return DIFFICULTY_GUIDE[key]


def build_explanation_prompt(niveau, cours, lecon, contenu, question):
    return f"""Contexte pédagogique EduBac :
Niveau : {niveau}
Cours : {cours}
Leçon : {lecon}

Contenu de la leçon :
{contenu}

Question de l'élève :
{question}
"""


QUIZ_LATEX_RULES = r"""LaTeX : dans `text`, `choices[].text`, `explanation` et `hint`, encadre chaque expression mathématique par `$...$` (pas `$$`, pas de `$` monétaire, pas d'ASCII du type `sqrt(` ni de glyphes Unicode). Dans le JSON, double chaque antislash : `\\frac`, `\\forall`, `\\neq`. Exemple : "text": "Montre que $\\forall x \\in \\mathbb{R},\\ x \\neq 0 \\Rightarrow |x| > 0$."
"""


def build_quiz_prompt(niveau, cours, lecon, contenu, count, difficulty):
    guide = difficulty_instructions(difficulty)
    return f"""Génère un quiz de mathématiques STRICTEMENT basé sur le contenu suivant.

Niveau : {niveau}
Cours : {cours}
Leçon : {lecon}

Contenu :
{contenu}

Nombre de questions : {count}
Niveau de difficulté demandé : {difficulty}

{guide}

{QUIZ_LATEX_RULES}
"""


def format_response(raw_text: str) -> str:
    """Nettoyage simple de la réponse LLM."""
    return raw_text.strip()
