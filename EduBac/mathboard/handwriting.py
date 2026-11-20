"""Écriture manuscrite → texte et formules (tableau mathématique).

Le professeur sélectionne ses traits au stylet et clique sur « Convertir » :
le navigateur envoie une image PNG de ces seuls traits, Claude (lecture
d'image) la transcrit en lignes de segments « texte » / « formule (LaTeX) »,
que le professeur relit et corrige avant de les insérer sur le tableau.

Désactivé par défaut. Pour l'activer (.env) :
    MATHBOARD_HANDWRITING_ENABLED=1
    ANTHROPIC_API_KEY=<clé>
et installer le paquet : pip install -r requirements-ecriture.txt

Seule l'image des traits sélectionnés est envoyée (aucun nom, aucune autre
donnée du tableau). Réservé aux enseignants et administrateurs.
"""
import base64
import binascii
import io
import json
import logging

from django.conf import settings

logger = logging.getLogger(__name__)

MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_SIDE = 1568          # au-delà, l'image est réduite sans perte utile de lisibilité
MAX_LINES = 40
MAX_SEGMENT = 2000

SYSTEM_PROMPT = """You transcribe handwriting from a math teacher's whiteboard (Moroccan high school: French and Arabic, \
mathematics). The image contains only the teacher's pen strokes on a white background.

Transcribe exactly what is written, line by line, top to bottom. Do not solve, complete, correct or rephrase anything, \
even if it contains a mistake. Keep the original language of each word (Arabic stays Arabic, French stays French).

Split every line into segments, in reading order:
- "text": ordinary words, in the original language and spelling.
- "math": any formula, expression, number with operators, set, interval, equation or inequality, written as LaTeX \
without delimiters (no $ or \\( \\)). Use standard LaTeX: \\frac, \\sqrt, ^, _, \\lim_{x \\to a}, \\int, \\in, \\mathbb{R}, \\leq, \\infty...

A line written only with symbols is a single "math" segment. Ignore stray marks, crossed-out parts and scribbles. \
If nothing is legible, return no lines and set "unreadable" to true."""

OUTPUT_SCHEMA = {
    'type': 'object',
    'properties': {
        'lines': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'segments': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'kind': {'type': 'string', 'enum': ['text', 'math']},
                                'content': {'type': 'string'},
                            },
                            'required': ['kind', 'content'],
                            'additionalProperties': False,
                        },
                    },
                },
                'required': ['segments'],
                'additionalProperties': False,
            },
        },
        'unreadable': {'type': 'boolean'},
    },
    'required': ['lines', 'unreadable'],
    'additionalProperties': False,
}


class HandwritingError(Exception):
    """Message destiné à l'utilisateur (français)."""


def enabled():
    return bool(settings.MATHBOARD_HANDWRITING_ENABLED and settings.ANTHROPIC_API_KEY)


def prepare_image(data_url):
    """Data URL PNG → octets PNG vérifiés et réduits si nécessaire."""
    from PIL import Image, UnidentifiedImageError
    prefix = 'data:image/png;base64,'
    if not isinstance(data_url, str) or not data_url.startswith(prefix):
        raise HandwritingError('Image des traits manquante.')
    try:
        raw = base64.b64decode(data_url[len(prefix):], validate=True)
    except (binascii.Error, ValueError):
        raise HandwritingError('Image des traits illisible.')
    if len(raw) > MAX_IMAGE_BYTES:
        raise HandwritingError('Sélection trop grande : convertissez-la en plusieurs fois.')
    try:
        image = Image.open(io.BytesIO(raw))
        if image.format != 'PNG':
            raise HandwritingError('Image des traits illisible.')
        image.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise HandwritingError('Image des traits illisible.')
    if max(image.size) > MAX_SIDE:
        image.thumbnail((MAX_SIDE, MAX_SIDE))
        out = io.BytesIO()
        image.save(out, 'PNG', optimize=True)
        raw = out.getvalue()
    return raw


def recognize(png):
    """Transcrit l'image ; renvoie une liste de lignes [{'segments': [...]}]."""
    data = _ask_claude(png)
    if not isinstance(data, dict):
        raise HandwritingError('Réponse inattendue du service de reconnaissance.')
    lines = []
    for line in (data.get('lines') or [])[:MAX_LINES]:
        segments = []
        for segment in (line or {}).get('segments') or []:
            kind = segment.get('kind')
            content = ' '.join(str(segment.get('content') or '').split())[:MAX_SEGMENT]
            if kind in ('text', 'math') and content:
                segments.append({'kind': kind, 'content': content})
        if segments:
            lines.append({'segments': segments})
    if not lines:
        raise HandwritingError('Écriture illisible : écrivez plus grand ou sélectionnez moins de traits.')
    return lines


def _ask_claude(png):
    try:
        import anthropic
    except ImportError:
        logger.error('Reconnaissance d’écriture activée mais paquet « anthropic » absent '
                     '(pip install -r requirements-ecriture.txt).')
        raise HandwritingError('La reconnaissance d’écriture n’est pas installée sur ce serveur.')

    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY, timeout=60.0, max_retries=1)
    try:
        response = client.beta.messages.create(
            model=settings.MATHBOARD_HANDWRITING_MODEL,
            max_tokens=8000,
            # Si le modèle décline la demande, l'API la relance sur un modèle de repli.
            betas=['server-side-fallback-2026-07-01'],
            fallbacks='default',
            # Transcription simple : peu de réflexion, réponse plus rapide.
            output_config={'effort': 'low', 'format': {'type': 'json_schema', 'schema': OUTPUT_SCHEMA}},
            system=SYSTEM_PROMPT,
            messages=[{
                'role': 'user',
                'content': [
                    {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png',
                                                 'data': base64.standard_b64encode(png).decode('ascii')}},
                    {'type': 'text', 'text': 'Transcribe this handwriting.'},
                ],
            }],
        )
    except anthropic.RateLimitError:
        raise HandwritingError('Service de reconnaissance saturé : réessayez dans une minute.')
    except anthropic.APIStatusError as exc:
        logger.error('Reconnaissance d’écriture : erreur %s (%s)', exc.status_code, exc.message)
        raise HandwritingError('Le service de reconnaissance a rencontré une erreur. Réessayez.')
    except anthropic.APIConnectionError:
        raise HandwritingError('Service de reconnaissance injoignable depuis le serveur.')

    if response.stop_reason == 'refusal':
        raise HandwritingError('Le service a refusé de transcrire cette image.')
    if response.stop_reason == 'max_tokens':
        raise HandwritingError('Sélection trop longue : convertissez-la en plusieurs fois.')
    text = next((block.text for block in response.content if block.type == 'text'), '')
    try:
        return json.loads(text)
    except ValueError:
        raise HandwritingError('Réponse inattendue du service de reconnaissance.')
