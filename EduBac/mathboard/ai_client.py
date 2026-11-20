"""Appel du service IA indépendant (FastAPI, dossier ai_service/).

Le navigateur parle uniquement à Django ; Django ajoute le contexte pédagogique
(niveau, chapitre, leçon, contenu de la page) et un jeton de service. Les clés
des fournisseurs d'IA ne quittent jamais le service IA.
"""
import json
import re
import urllib.error
import urllib.request

from django.conf import settings

ACTIONS = ('analyze', 'solve', 'explain', 'verify', 'hint', 'exercises')
FORBIDDEN_LATEX = re.compile(r'\\(href|url|html\w*|class|cssId|style|data|require)\b')
MAX_BLOCKS = 40


class AIServiceError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def _text(value, limit):
    return str(value or '').strip()[:limit]


def _level(document, user):
    if document.level:
        return document.level
    profile = getattr(user, 'student_profile', None) if user.is_student() else None
    return getattr(profile, 'niveau', '') if profile else (document.classroom.niveau if document.classroom else '')


def board_summary(document, page_uid):
    """Texte et formules de la page affichée (ce que l'IA doit « voir »)."""
    page = document.pages.filter(uid=str(page_uid or '')[:64]).first() or document.pages.first()
    items = []
    for obj in (page.content.values() if page else []):
        kind = obj.get('type')
        if kind == 'math' and obj.get('latex'):
            items.append({'type': 'math', 'content': _text(obj['latex'], 1500)})
        elif kind in ('i-text', 'textbox', 'text') and obj.get('text'):
            items.append({'type': 'text', 'content': _text(obj['text'], 1500)})
        elif kind == 'geometry' and obj.get('script'):
            items.append({'type': 'figure', 'content': _text(obj['script'], 1500)})
        if len(items) >= 40:
            break
    return items


def _clean_blocks(blocks):
    clean = []
    for block in blocks if isinstance(blocks, list) else []:
        if not isinstance(block, dict):
            continue
        kind, content = block.get('type'), _text(block.get('content'), 4000)
        if not content:
            continue
        if kind == 'math' and FORBIDDEN_LATEX.search(content):
            kind = 'text'
        if kind in ('text', 'math'):
            clean.append({'type': kind, 'content': content})
        if len(clean) >= MAX_BLOCKS:
            break
    return clean


def _post(url, payload, headers, timeout):
    """POST JSON (bibliothèque standard). Renvoie (statut HTTP, corps)."""
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode('utf-8'), method='POST',
        headers={'Content-Type': 'application/json', 'Accept': 'application/json', **headers})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 (URL de configuration)
            return response.status, response.read(1_000_000)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(10_000)


def call_ai_service(action, document, user, data):
    if action not in ACTIONS:
        raise AIServiceError(404, 'Action de l’assistant inconnue.')
    if not settings.MATHBOARD_AI_URL:
        raise AIServiceError(503, 'L’assistant IA n’est pas encore configuré sur ce serveur.')
    data = data if isinstance(data, dict) else {}
    question = _text(data.get('question'), 4000)
    latex = _text(data.get('latex'), 2000)
    if action != 'exercises' and not (question or latex or data.get('student_answer')):
        raise AIServiceError(400, 'Écrivez une question ou sélectionnez une formule.')
    payload = {
        'level': _level(document, user),
        'chapter': document.chapter or '',
        'lesson': document.lesson.title if document.lesson_id else '',
        'role': 'teacher' if user.is_teacher() else 'student',
        'question': question,
        'latex': latex,
        'student_answer': _text(data.get('student_answer'), 2000),
        'expected': _text(data.get('expected'), 2000),
        'count': max(1, min(5, int(data.get('count') or 1))) if str(data.get('count', '1')).isdigit() else 1,
        'difficulty': _text(data.get('difficulty'), 20),
        'board': board_summary(document, data.get('page')),
    }
    try:
        status, raw = _post(f'{settings.MATHBOARD_AI_URL}/v1/{action}', payload,
                            {'X-Service-Token': settings.MATHBOARD_AI_TOKEN}, settings.MATHBOARD_AI_TIMEOUT)
    except OSError:
        raise AIServiceError(502, 'Le service IA ne répond pas. Réessayez dans un instant.') from None
    if status == 429:
        raise AIServiceError(429, 'Trop de demandes à l’assistant. Patientez un peu.')
    if status == 503:
        raise AIServiceError(503, 'Aucun fournisseur d’IA n’est disponible pour le moment.')
    if status != 200:
        raise AIServiceError(502, 'Le service IA a rencontré un problème.')
    try:
        body = json.loads(raw.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        raise AIServiceError(502, 'Réponse illisible du service IA.') from None
    result = {
        'reply': _text(body.get('reply'), 6000),
        'blocks': _clean_blocks(body.get('blocks')),
        'provider': _text(body.get('provider'), 40),
    }
    verification = body.get('verification')
    if isinstance(verification, dict):
        result['verification'] = {
            'correct': verification.get('correct') if isinstance(verification.get('correct'), bool) else None,
            'method': _text(verification.get('method'), 20),
            'details': _text(verification.get('details'), 2000),
        }
    return result
