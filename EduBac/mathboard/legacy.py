"""Conversion d'un tableau de l'ancien module (whiteboard) en document du tableau
mathématique. L'ancien tableau n'est ni modifié ni supprimé.

Correspondances :
  stroke (crayon, surligneur)    → path (Fabric)
  line, arrow, triangle          → path
  rect, circle                   → rect, circle
  text, note                     → i-text (note : fond jaune ; arabe : de droite à gauche)
  math (LaTeX)                   → math
  graph (expression)             → geometry « f(x) = … »
  plot (commandes du repère)     → geometry (commandes reconnues ; les autres en commentaire)
  vartable, probtree             → i-text (texte d'origine)
  image                          → image (copiée dans media/mathboard/)
Non convertis (comptés dans le rapport) : coups de gomme, réponses d'élèves aux repères.
"""
import base64
import binascii
import io
import math
import re
import uuid

from django.core.files.storage import default_storage
from django.db import transaction

from .images import save_image, storage_name
from .models import WhiteboardDocument, WhiteboardPage
from .operations import MAX_OBJECTS_PER_PAGE, OpError, _check_object

BACKGROUNDS = {'plain': 'blank', 'grid': 'grid', 'ruled': 'lines', 'dots': 'dots'}
ARABIC = re.compile(r'^[^A-Za-z؀-ۿ]*[؀-ۿ]')
GEOMETRY_COMMANDS = {
    'segment', 'droite', 'demidroite', 'cercle', 'triangle', 'polygone', 'angle', 'vecteur', 'milieu',
    'perpendiculaire', 'parallele', 'intersection', 'tangente', 'verticale', 'texte',
}
DATA_URL = re.compile(r'^data:image/(png|jpeg|webp);base64,(.+)$', re.S)


def _num(value, default=0.0):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _color(value, default='#212529'):
    value = str(value or '')
    return value if re.match(r'^#[0-9a-fA-F]{3,8}$|^rgba?\([\d\s.,%]+\)$', value) else default


def _path(commands, color, width, opacity=1.0, closed=False):
    """Chemin Fabric à partir de points absolus [(x, y), …] (premier = M)."""
    points = [(x, y) for x, y in commands]
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    path = [['M', points[0][0], points[0][1]]] + [['L', x, y] for x, y in points[1:]]
    if len(points) == 1:
        path.append(['L', points[0][0] + 0.01, points[0][1]])
    if closed:
        path.append(['Z'])
    return {'type': 'path', 'path': path, 'left': min(xs) - width / 2, 'top': min(ys) - width / 2,
            'stroke': color, 'strokeWidth': width, 'fill': None, 'opacity': opacity,
            'strokeLineCap': 'round', 'strokeLineJoin': 'round', 'strokeUniform': True}


def _segments_path(segments, color, width):
    """Plusieurs segments (flèche) dans un seul chemin."""
    path, xs, ys = [], [], []
    for (x1, y1), (x2, y2) in segments:
        path += [['M', x1, y1], ['L', x2, y2]]
        xs += [x1, x2]
        ys += [y1, y2]
    return {'type': 'path', 'path': path, 'left': min(xs) - width / 2, 'top': min(ys) - width / 2,
            'stroke': color, 'strokeWidth': width, 'fill': None, 'strokeLineCap': 'round',
            'strokeLineJoin': 'round', 'strokeUniform': True}


def _text(text, x, y, color, size, note=False):
    font_size = round(_num(size, 3) * 4 + 12, 2)
    model = {'type': 'i-text', 'text': str(text)[:5000], 'left': x, 'top': y - font_size * 0.85,
             'fontSize': font_size, 'fill': color, 'fontFamily': 'system-ui, sans-serif'}
    if note:
        model['backgroundColor'] = '#f4e6cb'
    if ARABIC.match(model['text']):
        model.update({'direction': 'rtl', 'textAlign': 'right'})
    return model


def _plot_script(item_lines):
    lines = []
    for raw in item_lines:
        line = str(raw or '').strip()
        if not line:
            continue
        # Ancienne syntaxe : « ; » sépare les arguments et « , » est la virgule décimale.
        converted = re.sub(r'(?<=\d),(?=\d)', '.', line).replace(';', ',')
        command = re.match(r'^\s*(?:\w+\s*=\s*)?([A-Za-zÀ-ÿ]+)\s*\(', converted)
        is_point = re.match(r'^\s*\w+\s*=\s*\(', converted)
        is_function = re.match(r'^\s*\w+\s*\(\s*x\s*\)\s*=', converted)
        known = command and command.group(1).lower().replace('é', 'e').replace('è', 'e') in GEOMETRY_COMMANDS
        lines.append(converted if (is_point or is_function or known) else '# ' + line)
    return '\n'.join(lines)


def _store_image(src, document_id):
    """Copie l'image dans media/mathboard/ et renvoie (url, largeur, hauteur) ou None."""
    from PIL import Image
    data = None
    match = DATA_URL.match(str(src or ''))
    if match:
        try:
            data = base64.b64decode(match.group(2), validate=False)
        except (binascii.Error, ValueError):
            return None
    elif str(src or '').startswith('/media/') or storage_name(src):
        name = storage_name(src) or str(src)[len('/media/'):]
        if '..' in name or not default_storage.exists(name):
            return None
        with default_storage.open(name, 'rb') as handle:
            data = handle.read()
    if not data:
        return None
    try:
        image = Image.open(io.BytesIO(data))
        kind = image.format
        image.load()
    except Exception:
        return None
    if kind not in ('PNG', 'JPEG', 'WEBP'):
        return None
    image.thumbnail((1600, 1600))
    if kind == 'JPEG' and image.mode not in ('RGB', 'L'):
        image = image.convert('RGB')
    out = io.BytesIO()
    image.save(out, kind)
    extension = {'PNG': 'png', 'JPEG': 'jpg', 'WEBP': 'webp'}[kind]
    return save_image(document_id, out.getvalue(), extension), image.width, image.height


def convert_object(o, document_id):
    """Objet de l'ancien tableau → modèle du nouveau (ou None si non convertible)."""
    kind = o.get('type')
    color = _color(o.get('color'))
    width = max(0.5, min(60.0, _num(o.get('size'), 2)))
    if kind == 'stroke':
        if o.get('erase'):
            return None
        points = [(_num(p.get('x')), _num(p.get('y'))) for p in (o.get('points') or []) if isinstance(p, dict)]
        if not points:
            return None
        return _path(points[:5000], color, width, opacity=max(0.05, min(1.0, _num(o.get('alpha'), 1))))
    if kind in ('line', 'arrow'):
        x1, y1, x2, y2 = (_num(o.get(k)) for k in ('x1', 'y1', 'x2', 'y2'))
        if kind == 'line':
            return _path([(x1, y1), (x2, y2)], color, width)
        angle, head = math.atan2(y2 - y1, x2 - x1), 12 + width
        tips = [(x2 - head * math.cos(angle - s), y2 - head * math.sin(angle - s)) for s in (0.4, -0.4)]
        return _segments_path([((x1, y1), (x2, y2)), ((x2, y2), tips[0]), ((x2, y2), tips[1])], color, width)
    if kind == 'triangle':
        points = [(_num(o.get(f'x{i}')), _num(o.get(f'y{i}'))) for i in (1, 2, 3)]
        return _path(points, color, width, closed=True)
    if kind == 'rect':
        x, y, w, h = (_num(o.get(k)) for k in ('x', 'y', 'w', 'h'))
        return {'type': 'rect', 'left': min(x, x + w) - width / 2, 'top': min(y, y + h) - width / 2,
                'width': abs(w), 'height': abs(h), 'stroke': color, 'strokeWidth': width,
                'fill': 'transparent', 'strokeUniform': True}
    if kind == 'circle':
        cx, cy, r = _num(o.get('cx')), _num(o.get('cy')), abs(_num(o.get('r'), 10))
        return {'type': 'circle', 'left': cx - r - width / 2, 'top': cy - r - width / 2, 'radius': r,
                'stroke': color, 'strokeWidth': width, 'fill': 'transparent', 'strokeUniform': True}
    if kind in ('text', 'note'):
        if not str(o.get('text') or '').strip():
            return None
        return _text(o.get('text'), _num(o.get('x')), _num(o.get('y')), color, o.get('size'),
                     note=kind == 'note' or bool(o.get('note')))
    if kind == 'math':
        latex = str(o.get('latex') or '').strip()
        if not latex:
            return None
        return {'type': 'math', 'latex': latex[:5000], 'color': _color(o.get('color'), '#212529'),
                'fontSize': 24, 'left': _num(o.get('x')), 'top': _num(o.get('y'))}
    if kind == 'graph':
        expr = str(o.get('expr') or '').strip()
        if not expr:
            return None
        return {'type': 'geometry', 'script': f'f(x) = {expr}', 'view': {'xmin': -5, 'xmax': 5, 'ymin': -4, 'ymax': 4},
                'width': 480, 'height': 360, 'left': _num(o.get('x')), 'top': _num(o.get('y')),
                'scaleX': max(0.1, _num(o.get('w'), 480) / 480), 'scaleY': max(0.1, _num(o.get('h'), 360) / 360)}
    if kind == 'plot':
        view = o.get('view') if isinstance(o.get('view'), dict) else {}
        view = {k: _num(view.get(k), d) for k, d in (('xmin', -5), ('xmax', 5), ('ymin', -4), ('ymax', 4))}
        items = [item.get('line') for item in (o.get('items') or []) if isinstance(item, dict) and not item.get('hidden')]
        w, h = max(50.0, _num(o.get('w'), 560)), max(50.0, _num(o.get('h'), 420))
        return {'type': 'geometry', 'script': _plot_script(items), 'view': view, 'width': round(w), 'height': round(h),
                'left': _num(o.get('x')), 'top': _num(o.get('y'))}
    if kind in ('vartable', 'probtree'):
        if not str(o.get('text') or '').strip():
            return None
        return _text(o.get('text'), _num(o.get('x')), _num(o.get('y')) + 20, color, o.get('size'))
    if kind == 'image':
        stored = _store_image(o.get('src'), document_id)
        if stored is None:
            return None
        url, natural_w, natural_h = stored
        w, h = _num(o.get('w'), natural_w) or natural_w, _num(o.get('h'), natural_h) or natural_h
        return {'type': 'image', 'src': url, 'left': _num(o.get('x')), 'top': _num(o.get('y')),
                'scaleX': w / natural_w, 'scaleY': h / natural_h}
    return None


def convert_board(board, user):
    """Crée le document converti. Renvoie (document, {'converted': n, 'skipped': {type: n}})."""
    content = board.content if isinstance(board.content, dict) else {}
    objects = [o for o in content.get('objects') or [] if isinstance(o, dict)][:MAX_OBJECTS_PER_PAGE]
    report = {'converted': 0, 'skipped': {}}
    with transaction.atomic():
        document = WhiteboardDocument.objects.create(
            title=board.title[:200] or 'Tableau converti', owner=user, classroom=board.classroom,
            lesson=board.lesson, students_can_edit=board.students_can_edit, legacy_board=board)
        models = {}
        for index, obj in enumerate(objects):
            model = convert_object(obj, document.pk)
            kind = str(obj.get('type') or '?')
            if model is not None:
                model = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in model.items()}
                model['id'] = f'm{index:05d}{uuid.uuid4().hex[:8]}'
                model['z'] = index + 1
                try:
                    _check_object(model)
                except OpError:
                    model = None
            if model is None:
                if kind == 'stroke' and obj.get('erase'):
                    kind = 'gomme'
                report['skipped'][kind] = report['skipped'].get(kind, 0) + 1
                continue
            author = obj.get('by')
            model['_by'] = author if isinstance(author, int) else user.pk
            model['_rev'] = 0
            models[model['id']] = model
            report['converted'] += 1
        WhiteboardPage.objects.create(document=document, uid='page-1', position=0,
                                      background=BACKGROUNDS.get(content.get('background'), 'grid'), content=models)
    return document, report
