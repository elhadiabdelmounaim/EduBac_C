"""Bounded data-only contracts at the student / model trust boundaries."""
import base64
import binascii
import io
import math

from PIL import Image, UnidentifiedImageError


class TutorInputError(ValueError):
    pass


def text(value, name, limit=4000, required=False):
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise TutorInputError(f'{name} : texte {"requis, " if required else ""}limité à {limit} caractères.')
    return value.strip()


def image_data(value):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 2 * 1024 * 1024:
        raise TutorInputError('Image trop volumineuse (2 Mo maximum).')
    try:
        header, encoded = value.split(',', 1)
        formats = {'data:image/png;base64': 'PNG', 'data:image/jpeg;base64': 'JPEG',
                   'data:image/webp;base64': 'WEBP'}
        if header not in formats:
            raise ValueError()
        raw = base64.b64decode(encoded, validate=True)
        with Image.open(io.BytesIO(raw)) as image:
            if image.format != formats[header] or image.width * image.height > 16_000_000:
                raise ValueError()
            image.verify()
    except (ValueError, binascii.Error, OSError, UnidentifiedImageError, Image.DecompressionBombError):
        raise TutorInputError('Image invalide. Utilise PNG, JPEG ou WebP.') from None
    return value


def validate_request(data):
    if not isinstance(data, dict):
        raise TutorInputError('La requête doit être un objet JSON.')
    question = text(data.get('question'), 'Question', required=True)
    mode, intent = data.get('mode', 'hint'), data.get('intent', 'ask')
    if mode not in ('hint', 'explanation', 'solution'):
        raise TutorInputError('Niveau d’aide invalide.')
    if intent not in ('ask', 'explain', 'hint', 'verify', 'solve', 'rule'):
        raise TutorInputError('Action pédagogique invalide.')
    # Explicit contextual actions select their corresponding pedagogical depth.
    mode = {'hint': 'hint', 'solve': 'solution', 'explain': 'explanation',
            'rule': 'explanation', 'verify': 'explanation'}.get(intent, mode)
    objects = data.get('objects', [])
    if not isinstance(objects, list) or len(objects) > 250:
        raise TutorInputError('Envoie au maximum 250 éléments du tableau.')
    clean, ids = [], set()
    numeric = ('x', 'y', 'w', 'h', 'x1', 'y1', 'x2', 'y2', 'x3', 'y3', 'cx', 'cy',
               'r', 'size', 'xmin', 'xmax', 'ymin', 'ymax', 'angle')
    types = ('path', 'stroke', 'text', 'note', 'math', 'line', 'arrow', 'rect',
             'circle', 'triangle', 'image', 'graph', 'ruler', 'protractor')
    for obj in objects:
        if not isinstance(obj, dict) or obj.get('type') not in types:
            raise TutorInputError('Type d’élément du tableau invalide.')
        oid = text(obj.get('id'), 'Identifiant', 100, True)
        if oid in ids:
            raise TutorInputError('Identifiants dupliqués dans le tableau.')
        ids.add(oid)
        item = {'id': oid, 'type': obj['type']}
        for key in ('text', 'latex', 'expr', 'label', 'geometry'):
            if key in obj:
                item[key] = text(obj[key], key)
        for key in numeric:
            if key in obj:
                val = obj[key]
                if isinstance(val, bool) or not isinstance(val, (float, int)) or not math.isfinite(val) or abs(val) > 1_000_000:
                    raise TutorInputError('Coordonnée du tableau invalide.')
                item[key] = val
        if 'points' in obj:
            points = obj['points']
            if not isinstance(points, list) or len(points) > 10000:
                raise TutorInputError('Tracé trop long.')
            sampled = points[::max(1, len(points) // 200)][:200]
            item['points'] = []
            for point in sampled:
                if not isinstance(point, dict) or any(
                    isinstance(point.get(k), bool) or not isinstance(point.get(k), (int, float))
                    or not math.isfinite(point[k]) or abs(point[k]) > 1_000_000 for k in ('x', 'y')
                ):
                    raise TutorInputError('Point invalide.')
                item['points'].append({'x': point['x'], 'y': point['y']})
        # No raw HTML, source URLs, embedded images, or runtime functions in the prompt.
        if obj['type'] == 'image':
            item['description'] = 'Image : voir la pièce jointe si fournie, sinon demander une capture.'
        clean.append(item)
    selected = data.get('selected_id')
    if selected is not None and (not isinstance(selected, str) or selected not in ids):
        raise TutorInputError('L’élément sélectionné est absent du tableau.')
    attempts = data.get('previous_attempts', [])
    if not isinstance(attempts, list) or len(attempts) > 10:
        raise TutorInputError('Dix tentatives au maximum.')
    return {
        'question': question, 'mode': mode, 'intent': intent, 'objects': clean,
        'selected_id': selected, 'previous_attempts': [text(v, 'Tentative') for v in attempts],
        'exercise': text(data.get('exercise', ''), 'Exercice'), 'image': image_data(data.get('image')),
    }


def validate_response(data, intent):
    if not isinstance(data, dict):
        raise TutorInputError('Réponse IA invalide.')
    reply = text(data.get('reply'), 'Réponse IA', 12000, True)
    actions = data.get('actions', [])
    if not isinstance(actions, list) or len(actions) > 30:
        raise TutorInputError('Actions IA invalides.')
    safe = []
    for action in actions:
        if not isinstance(action, dict) or set(action) != {'action', 'content'}:
            raise TutorInputError('Structure d’action IA invalide.')
        if action['action'] not in ('add_text', 'add_equation', 'add_note'):
            raise TutorInputError('Action IA non autorisée.')
        content = text(action['content'], 'Contenu', required=True)
        if action['action'] == 'add_equation':
            # Some models include display delimiters despite the schema prompt.
            # KaTeX.render expects the expression only, not \[...\] or $...$.
            for start, end in ((r'\[', r'\]'), (r'\(', r'\)'), ('$$', '$$'), ('$', '$')):
                if content.startswith(start) and content.endswith(end):
                    content = content[len(start):-len(end)].strip()
                    break
            if not content:
                raise TutorInputError('Équation vide.')
        safe.append({'action': action['action'], 'content': content})
    verification = data.get('verification')
    if verification is not None:
        fields = ('error_step', 'reason', 'review_step', 'rule')
        if not isinstance(verification, dict) or type(verification.get('correct')) not in (bool, type(None)):
            raise TutorInputError('Vérification IA invalide.')
        verification = {'correct': verification.get('correct'),
                        **{key: text(verification.get(key, ''), key, 2000) for key in fields}}
        if not verification['reason']:
            raise TutorInputError('Justification de vérification manquante.')
    if intent == 'verify' and verification is None:
        raise TutorInputError('Vérification manquante.')
    return {'reply': reply, 'actions': safe, 'verification': verification}
