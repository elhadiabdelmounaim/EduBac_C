"""
Templates de prompts pour l'assistant IA EduBac.
"""

DIFFICULTY_GUIDE = {
    "facile": """DIFFICULTÉ FACILE — règles obligatoires :
- Questions directes d'application immédiate du cours
- Une seule notion simple par question
- Calculs courts (1 à 2 étapes maximum)
- Distractors (mauvaises réponses) évidents ou erreurs de signe/calcul basiques
- Pas de pièges, pas de cas particuliers, pas de démonstration
- Formules utilisées telles quelles, sans manipulation complexe
- Niveau : vérification que l'élève a lu/retenu le cours""",

    "moyen": """DIFFICULTÉ MOYENNE — règles obligatoires :
- Application du cours avec 2 à 3 étapes de raisonnement
- Combinaison possible de deux notions de la leçon
- Calculs standard du programme (factorisation, équation simple, dérivée directe…)
- Distractors plausibles (erreurs classiques d'élèves)
- Peut inclure un cas un peu moins direct, mais toujours dans le cours
- Pas de démonstration longue ni d'exercice type bac complet""",

    "difficile": """DIFFICULTÉ DIFFICILE — règles obligatoires :
- Raisonnement multi-étapes (3 étapes ou plus)
- Synthèse de plusieurs notions de la leçon (voire leçon liée si dans le contenu)
- Pièges classiques du bac (domaine de définition, cas particuliers, conditions)
- Distractors très proches de la bonne réponse (erreurs subtiles)
- Peut demander justification, choix de méthode, ou interprétation
- Niveau proche d'un exercice d'examen / bac, tout en restant STRICTEMENT sur le contenu fourni
- Énoncés plus riches, mais clairs et en français""",
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
"""


def format_response(raw_text: str) -> str:
    """Nettoyage simple de la réponse LLM."""
    return raw_text.strip()
