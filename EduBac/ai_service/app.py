"""Service IA mathématique EduBac (FastAPI), indépendant de Django.

Lancement : uvicorn ai_service.app:app --host 127.0.0.1 --port 8100
(depuis le dossier EduBac/, pour que le module partagé edubac_math soit trouvé).

Points d'accès (JSON, jeton X-Service-Token obligatoire) :
  POST /v1/analyze    analyser une expression ou une production d'élève
  POST /v1/solve      résoudre un exercice (résultat vérifié par SymPy si possible)
  POST /v1/explain    expliquer une solution ou une notion
  POST /v1/verify     vérifier la réponse d'un élève (SymPy d'abord, puis le modèle)
  POST /v1/hint       donner un indice sans la solution
  POST /v1/exercises  générer des exercices du niveau et du chapitre
  GET  /health
"""
import json
import os
import re
import secrets
import sys
from pathlib import Path
from typing import List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # edubac_math

from edubac_math import ParseError, compute, latex_to_text  # noqa: E402

from .curriculum import level_label  # noqa: E402
from .providers import ProviderError, complete_json  # noqa: E402

app = FastAPI(title='EduBac — service IA mathématique', version='1.0')
FORBIDDEN_LATEX = re.compile(r'\\(href|url|html\w*|class|cssId|style|data|require)\b')

INSTRUCTIONS = {
    'analyze': 'Analyse le contenu : nature de l’objet mathématique, erreurs éventuelles, notions en jeu.',
    'solve': 'Résous l’exercice étape par étape, avec la rédaction attendue au lycée marocain.',
    'explain': 'Explique clairement la notion ou la démarche, avec un exemple court.',
    'verify': 'Vérifie la réponse de l’élève : dis si elle est juste, et sinon où se trouve l’erreur, sans tout refaire.',
    'hint': 'Donne UN indice progressif qui fait avancer l’élève, sans donner la solution ni le résultat final.',
    'exercises': 'Propose des exercices originaux adaptés au niveau et au chapitre, avec réponse et indice.',
}
SYSTEM = (
    'Tu es un professeur de mathématiques du lycée marocain (programme officiel, enseignement en français). '
    'Réponds en français, avec la terminologie marocaine (Tronc commun, 1re et 2e année du Bac, '
    '« ensemble de définition », « tableau de variations », « log » = logarithme décimal, « ln » = népérien). '
    'Réponds UNIQUEMENT par un objet JSON : {"reply": "résumé court", "blocks": [{"type": "text"|"math", '
    '"content": "..."}]}. Les blocs "math" contiennent du LaTeX seul (sans $). '
    'Pour « verify », ajoute "verification": {"correct": true|false|null, "details": "..."}. '
    'Pour « exercises », renvoie {"reply": "...", "exercises": [{"statement": [blocs], "answer": "LaTeX", '
    '"hint": "texte"}]}. Si un résultat SymPy est fourni, il est exact : ta réponse doit le respecter.'
)


class Item(BaseModel):
    type: str = Field(max_length=10)
    content: str = Field(max_length=2000)


class Task(BaseModel):
    level: str = Field('', max_length=50)
    chapter: str = Field('', max_length=200)
    lesson: str = Field('', max_length=255)
    role: str = Field('student', max_length=10)
    question: str = Field('', max_length=4000)
    latex: str = Field('', max_length=2000)
    student_answer: str = Field('', max_length=2000)
    expected: str = Field('', max_length=2000)
    count: int = Field(1, ge=1, le=5)
    difficulty: str = Field('', max_length=20)
    board: List[Item] = Field(default_factory=list, max_length=40)


class Block(BaseModel):
    type: str
    content: str


class Verification(BaseModel):
    correct: Optional[bool] = None
    method: str = ''
    details: str = ''


class Answer(BaseModel):
    reply: str
    blocks: List[Block]
    verification: Optional[Verification] = None
    provider: str = ''


def require_token(x_service_token: str = Header(default='')):
    expected = os.getenv('AI_SERVICE_TOKEN', '')
    if not expected or not secrets.compare_digest(x_service_token, expected):
        raise HTTPException(status_code=401, detail='Jeton de service invalide.')


def _as_text(value):
    """Formule LaTeX ou saisie libre → syntaxe de l'analyseur SymPy."""
    value = (value or '').strip()
    if not value:
        return ''
    try:
        return latex_to_text(value) if '\\' in value or '{' in value else value
    except ParseError:
        return value


def sympy_facts(action, task):
    """Résultats exacts calculés par SymPy, transmis au modèle et à l'élève."""
    facts = {}
    expression = _as_text(task.latex)
    if action == 'verify' and task.student_answer and task.expected:
        result = compute('equal', _as_text(task.student_answer), other=_as_text(task.expected))
        if result.get('ok'):
            facts['verification'] = bool(result.get('equal'))
    if action in ('solve', 'analyze') and expression:
        kind = 'solve' if re.search(r'(<=|>=|!=|=|<|>|;)', expression) else 'simplify'
        result = compute(kind, expression)
        if result.get('ok'):
            facts[kind] = result['latex']
    return facts


def _blocks(raw):
    blocks = []
    for block in raw if isinstance(raw, list) else []:
        if not isinstance(block, dict):
            continue
        kind, content = block.get('type'), str(block.get('content') or '').strip()[:4000]
        if not content or kind not in ('text', 'math'):
            continue
        if kind == 'math':
            content = content.strip('$ ')
            if FORBIDDEN_LATEX.search(content):
                kind = 'text'
        blocks.append(Block(type=kind, content=content))
    return blocks[:40]


def run(action, task):
    facts = sympy_facts(action, task)
    user = json.dumps({
        'action': action, 'instruction': INSTRUCTIONS[action], 'niveau': level_label(task.level),
        'chapitre': task.chapter, 'lecon': task.lesson, 'role': task.role, 'question': task.question,
        'latex': task.latex, 'reponse_eleve': task.student_answer, 'reponse_attendue': task.expected,
        'nombre': task.count, 'difficulte': task.difficulty,
        'tableau': [item.model_dump() for item in task.board], 'resultats_sympy': facts,
    }, ensure_ascii=False)
    try:
        data, provider = complete_json(SYSTEM, user)
    except ProviderError:
        raise HTTPException(status_code=503, detail='Aucun fournisseur d’IA disponible.') from None

    blocks = _blocks(data.get('blocks'))
    if action == 'exercises':
        for number, exercise in enumerate(data.get('exercises') or [], start=1):
            if not isinstance(exercise, dict):
                continue
            blocks.append(Block(type='text', content=f'Exercice {number}'))
            blocks.extend(_blocks(exercise.get('statement')))
            if exercise.get('hint'):
                blocks.append(Block(type='text', content=f"Indice : {str(exercise['hint'])[:1000]}"))
            if exercise.get('answer') and task.role == 'teacher':
                blocks.append(Block(type='text', content='Réponse :'))
                blocks.extend(_blocks([{'type': 'math', 'content': exercise['answer']}]))
    for kind in ('solve', 'simplify'):
        if kind in facts:
            blocks.insert(0, Block(type='math', content=facts[kind]))
            blocks.insert(0, Block(type='text', content='Résultat exact (SymPy) :'))
    verification = None
    if action == 'verify':
        model_view = data.get('verification') if isinstance(data.get('verification'), dict) else {}
        if 'verification' in facts:
            verification = Verification(correct=facts['verification'], method='sympy',
                                        details=str(model_view.get('details') or '')[:2000])
        else:
            correct = model_view.get('correct')
            verification = Verification(correct=correct if isinstance(correct, bool) else None, method='modele',
                                        details=str(model_view.get('details') or '')[:2000])
    return Answer(reply=str(data.get('reply') or '')[:6000], blocks=blocks, verification=verification,
                  provider=provider)


@app.get('/health')
def health():
    return {'status': 'ok'}


def _endpoint(action):
    def handler(task: Task, _=Depends(require_token)):
        if action != 'exercises' and not (task.question or task.latex or task.student_answer):
            raise HTTPException(status_code=400, detail='Question manquante.')
        return run(action, task)
    handler.__name__ = f'v1_{action}'
    return handler


for _action in INSTRUCTIONS:
    app.post(f'/v1/{_action}', response_model=Answer)(_endpoint(_action))
