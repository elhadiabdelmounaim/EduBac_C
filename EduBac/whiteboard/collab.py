"""Collaboration sur un tableau : modifications élément par élément.

Chaque client envoie des opérations (ajout, modification, suppression…) au lieu
du contenu complet. Le serveur vérifie les droits de chaque opération, les
applique sous verrou et les numérote (révision). Les autres clients récupèrent
les opérations depuis leur dernière révision : par WebSocket quand il existe,
sinon par interrogation HTTP (PythonAnywhere en WSGI).
"""
import json
import math

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import WhiteboardBoard, WhiteboardOp, WhiteboardPresence

DRAW_TYPES = {'stroke', 'line', 'arrow', 'rect', 'circle', 'triangle', 'graph'}
TEXT_TYPES = {'text', 'note', 'math'}
IMAGE_TYPES = {'image'}
OBJECT_TYPES = DRAW_TYPES | TEXT_TYPES | IMAGE_TYPES
BACKGROUNDS = {'plain', 'grid', 'ruled', 'dots'}

MAX_OPS_PER_REQUEST = 200
MAX_OBJECT_BYTES = 300 * 1024
MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_OBJECTS = 5000
KEEP_OPS = 2000
ZONE_BASE_WIDTH = 1600  # largeur logique initiale du tableau (voir whiteboard.js)
MAX_ZONES = 4


class OpError(ValueError):
    pass


def category(obj):
    kind = obj.get('type')
    if kind == 'stroke' and obj.get('erase'):
        return 'delete'  # la gomme efface aussi le travail des autres
    if kind in TEXT_TYPES:
        return 'text'
    if kind in IMAGE_TYPES:
        return 'images'
    return 'draw'


def clean_object(raw):
    if not isinstance(raw, dict):
        raise OpError('Élément invalide.')
    obj = {k: v for k, v in raw.items() if isinstance(k, str) and not k.startswith('_') and k != 'by'}
    object_id = obj.get('id')
    if not isinstance(object_id, str) or not 0 < len(object_id) <= 100:
        raise OpError('Identifiant d’élément invalide.')
    if obj.get('type') not in OBJECT_TYPES:
        raise OpError('Type d’élément inconnu.')
    size = len(json.dumps(obj, separators=(',', ':')))
    limit = MAX_IMAGE_BYTES if obj['type'] == 'image' else MAX_OBJECT_BYTES
    if size > limit:
        raise OpError('Élément trop volumineux.')
    if obj['type'] == 'image':
        src = obj.get('src') or ''
        if not isinstance(src, str) or not (
            src.startswith(('data:image/png;base64,', 'data:image/jpeg;base64,',
                            'data:image/webp;base64,', 'data:image/gif;base64,', '/'))
        ):
            raise OpError('Image invalide.')
    return obj


def _num(value):
    return value if isinstance(value, (int, float)) and math.isfinite(value) else None


def center_x(obj):
    """Abscisse du centre de l'élément (pour les espaces de travail)."""
    kind = obj.get('type')
    if kind == 'stroke':
        xs = [_num(p.get('x')) for p in obj.get('points') or [] if isinstance(p, dict)]
        xs = [x for x in xs if x is not None]
        return (min(xs) + max(xs)) / 2 if xs else None
    if kind == 'circle':
        return _num(obj.get('cx'))
    if obj.get('x1') is not None:
        xs = [_num(obj.get(k)) for k in ('x1', 'x2', 'x3')]
        xs = [x for x in xs if x is not None]
        return (min(xs) + max(xs)) / 2 if xs else None
    x = _num(obj.get('x'))
    if x is None:
        return None
    w = _num(obj.get('w')) or 0
    return x + w / 2


def zone_index_for(x, count):
    width = ZONE_BASE_WIDTH / count
    return max(0, min(count - 1, int(x // width)))


def _in_zone(board, caps, obj):
    zone = caps.get('zone')
    if zone is None or not board.zones:
        return True
    x = center_x(obj)
    return x is not None and zone_index_for(x, len(board.zones)) == zone


def _authorize(board, user, caps, kind, obj, existing):
    """Renvoie un message d'erreur, ou '' si l'opération est permise."""
    if caps['manage'] or caps['control']:
        return ''
    if caps['locked']:
        return 'Le tableau est verrouillé.'
    if kind in ('clear', 'background'):
        return 'Seul l’enseignant peut effacer le tableau ou changer le fond.'
    if kind == 'delete':
        if existing is None:
            return ''
        own = existing.get('by') == user.pk
        if not (own and (caps['draw'] or caps['text'] or caps['images'])) and not caps['delete']:
            return 'Suppression non autorisée.'
        return '' if own or _in_zone(board, caps, existing) else 'Hors de votre espace de travail.'
    needed = category(obj)
    if not caps.get(needed):
        return {
            'draw': 'Dessin non autorisé.', 'text': 'Écriture non autorisée.',
            'images': 'Images non autorisées.', 'delete': 'La gomme demande le droit de suppression.',
        }[needed]
    if existing is not None and existing.get('by') != user.pk:
        return 'Vous ne pouvez modifier que vos propres éléments.'
    if not _in_zone(board, caps, obj):
        return 'Restez dans votre espace de travail.'
    return ''


def apply_ops(board_id, user, caps, ops, client=''):
    """Applique les opérations permises. Renvoie (révision, opérations appliquées, refus)."""
    if not isinstance(ops, list):
        raise OpError('Liste d’opérations invalide.')
    if len(ops) > MAX_OPS_PER_REQUEST:
        raise OpError('Trop de modifications en une fois.')
    applied, rejected = [], []
    with transaction.atomic():
        board = WhiteboardBoard.objects.select_for_update().get(pk=board_id)
        content = board.content if isinstance(board.content, dict) else {}
        objects = [o for o in content.get('objects') or [] if isinstance(o, dict)]
        index = {o.get('id'): i for i, o in enumerate(objects) if o.get('id')}
        background = content.get('background')
        revision = board.revision
        records = []
        contributions = 0
        for raw in ops:
            kind = raw.get('op') if isinstance(raw, dict) else None
            object_id = None
            try:
                if kind in ('add', 'update'):
                    obj = clean_object(raw.get('object'))
                    object_id = obj['id']
                    existing = objects[index[object_id]] if object_id in index else None
                    error = _authorize(board, user, caps, 'add', obj, existing)
                    if error:
                        raise OpError(error)
                    obj['by'] = existing.get('by', user.pk) if existing else user.pk
                    if existing is None:
                        if len(objects) >= MAX_OBJECTS:
                            raise OpError('Le tableau contient trop d’éléments.')
                        index[object_id] = len(objects)
                        objects.append(obj)
                    else:
                        objects[index[object_id]] = obj
                    payload, kind = {'object': obj}, ('update' if existing else 'add')
                    contributions += 1
                elif kind == 'delete':
                    object_id = str(raw.get('id') or '')[:100]
                    existing = objects[index[object_id]] if object_id in index else None
                    error = _authorize(board, user, caps, 'delete', None, existing)
                    if error:
                        raise OpError(error)
                    if existing is None:
                        continue
                    objects.pop(index[object_id])
                    index = {o.get('id'): i for i, o in enumerate(objects) if o.get('id')}
                    payload = {'id': object_id}
                elif kind == 'clear':
                    error = _authorize(board, user, caps, 'clear', None, None)
                    if error:
                        raise OpError(error)
                    objects, index = [], {}
                    payload = {}
                elif kind == 'background':
                    value = raw.get('background')
                    if value not in BACKGROUNDS:
                        raise OpError('Fond inconnu.')
                    error = _authorize(board, user, caps, 'background', None, None)
                    if error:
                        raise OpError(error)
                    background = value
                    payload = {'background': value}
                else:
                    raise OpError('Opération inconnue.')
            except OpError as exc:
                current = objects[index[object_id]] if object_id in index else None
                rejected.append({'id': object_id, 'op': kind, 'object': current, 'reason': str(exc)})
                continue
            revision += 1
            op = {'revision': revision, 'op': kind, 'author': user.pk, 'client': client, **payload}
            applied.append(op)
            records.append(WhiteboardOp(
                board=board, revision=revision, author=user, client=client[:64], kind=kind,
                object_id=object_id or '', payload=payload,
            ))
        if records:
            content = {**content, 'version': 1, 'objects': objects}
            if background:
                content['background'] = background
            WhiteboardBoard.objects.filter(pk=board.pk).update(
                content=content, revision=revision, updated_at=timezone.now(),
            )
            WhiteboardOp.objects.bulk_create(records)
            WhiteboardOp.objects.filter(board=board, revision__lte=revision - KEEP_OPS).delete()
            if contributions:
                presence, _ = WhiteboardPresence.objects.get_or_create(board=board, user=user)
                WhiteboardPresence.objects.filter(pk=presence.pk).update(
                    contributions=F('contributions') + contributions,
                )
    return revision, applied, rejected


def ensure_ids(board_id):
    """Donne un identifiant stable aux éléments des anciens tableaux (une seule fois)."""
    import uuid
    with transaction.atomic():
        board = WhiteboardBoard.objects.select_for_update().get(pk=board_id)
        content = board.content if isinstance(board.content, dict) else {}
        objects = content.get('objects') or []
        seen, changed = set(), False
        for obj in objects:
            if not isinstance(obj, dict):
                continue
            if not isinstance(obj.get('id'), str) or not obj['id'] or obj['id'] in seen:
                obj['id'] = 'wb-' + uuid.uuid4().hex
                changed = True
            seen.add(obj['id'])
        if changed:
            WhiteboardBoard.objects.filter(pk=board.pk).update(content={**content, 'objects': objects})
        return changed


def record_replace(board, user):
    """Contenu remplacé d'un bloc (ancienne sauvegarde globale) : les clients rechargent."""
    with transaction.atomic():
        locked = WhiteboardBoard.objects.select_for_update().only('revision').get(pk=board.pk)
        revision = locked.revision + 1
        WhiteboardBoard.objects.filter(pk=board.pk).update(revision=revision)
        WhiteboardOp.objects.create(board_id=board.pk, revision=revision, author=user, kind='replace')
    return revision


def ops_since(board, since):
    """Opérations après `since`, ou None s'il faut recharger tout le contenu."""
    if since >= board.revision:
        return []
    if since < 0:
        return None
    ops = list(WhiteboardOp.objects.filter(board=board, revision__gt=since).order_by('revision')[:500])
    if not ops or ops[0].revision != since + 1 or len(ops) < board.revision - since:
        return None
    if any(op.kind == 'replace' for op in ops):
        return None
    return [
        {'revision': op.revision, 'op': op.kind, 'author': op.author_id, 'client': op.client, **op.payload}
        for op in ops
    ]
