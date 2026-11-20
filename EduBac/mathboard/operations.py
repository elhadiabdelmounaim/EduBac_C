"""Moteur d'opérations : validation, application atomique, journal, versions.

Une opération (envoyée par le client) :
    {"op_id": "…", "kind": "object.add", "page": "<uid>", "object": {...}}
    {"op_id": "…", "kind": "object.update", "page": "<uid>", "id": "<objet>", "props": {...}}
    {"op_id": "…", "kind": "object.delete", "page": "<uid>", "id": "<objet>"}
    {"op_id": "…", "kind": "page.add", "page": {"uid": "…", "title": "…", "background": "grid"}, "index": 2}
    {"op_id": "…", "kind": "page.update", "page": "<uid>", "props": {"title": "…", "background": "axes"}}
    {"op_id": "…", "kind": "page.move", "page": "<uid>", "index": 0}
    {"op_id": "…", "kind": "page.delete", "page": "<uid>"}

Règles :
- chaque opération acceptée reçoit la révision suivante du document ;
- un op_id déjà enregistré n'est pas réappliqué (renvoi après coupure réseau) ;
- conflits : modification d'un objet supprimé ou création d'un identifiant
  existant → refus explicite ; modifications concurrentes d'un même objet →
  fusion propriété par propriété (la dernière arrivée l'emporte) ;
- un utilisateur « modification » ne modifie que ses propres objets ; un
  gestionnaire modifie tout ;
- les pages ne se suppriment / déplacent / renomment qu'avec le droit de gestion.
"""
import json
import math
import re

from django.db import transaction
from django.utils import timezone

from .access import LEVELS, access_level
from .models import WhiteboardDocument, WhiteboardOperation, WhiteboardPage, WhiteboardSnapshot

ID_RE = re.compile(r'^[A-Za-z0-9_\-:.]{1,64}$')
OBJECT_TYPES = {
    # Fabric.js
    'path', 'rect', 'circle', 'ellipse', 'triangle', 'line', 'polyline', 'polygon',
    'text', 'i-text', 'textbox', 'group', 'image',
    # EduBac : expression mathématique (MathLive/MathJax), figure JSXGraph, tableaux.
    'math', 'geometry', 'arrow', 'vartable', 'signtable',
}
PAGE_PROPS = {'title', 'background'}
MAX_OPS_PER_BATCH = 200
MAX_OBJECT_BYTES = 300 * 1024
MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_OBJECTS_PER_PAGE = 5000
MAX_PAGES = 200
MAX_DEPTH = 12
AUTO_SNAPSHOT_EVERY = 300           # opérations
AUTO_SNAPSHOT_KEEP = 50
IMAGE_SRC_RE = re.compile(r'^(data:image/(png|jpeg|webp);base64,[A-Za-z0-9+/=]+|/media/mathboard/[\w\-./]+)$')
FORBIDDEN_LATEX = re.compile(r'\\(href|url|html\w*|class|cssId|style|data|require)\b')


class OpError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def _check_value(value, depth=0):
    if depth > MAX_DEPTH:
        raise OpError('invalid', 'Objet trop imbriqué.')
    if isinstance(value, float) and not math.isfinite(value):
        raise OpError('invalid', 'Nombre invalide dans l’objet.')
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > 64:
                raise OpError('invalid', 'Propriété invalide.')
            _check_value(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _check_value(item, depth + 1)


def _check_object(obj):
    if obj.get('type') not in OBJECT_TYPES:
        raise OpError('invalid', 'Type d’objet non pris en charge.')
    _check_value(obj)
    size = len(json.dumps(obj))
    limit = MAX_IMAGE_BYTES if obj['type'] == 'image' else MAX_OBJECT_BYTES
    if size > limit:
        raise OpError('too_large', 'Objet trop volumineux.')
    if obj['type'] == 'image' and not IMAGE_SRC_RE.match(str(obj.get('src', ''))):
        raise OpError('invalid', 'Image invalide : PNG, JPEG ou WebP uniquement.')
    if obj['type'] == 'math' and FORBIDDEN_LATEX.search(str(obj.get('latex', ''))):
        raise OpError('invalid', 'Commande LaTeX non autorisée.')


def _require_id(value, what):
    if not isinstance(value, str) or not ID_RE.match(value):
        raise OpError('invalid', f'Identifiant de {what} invalide.')
    return value


def page_state(page):
    return {'uid': page.uid, 'title': page.title, 'background': page.background,
            'position': page.position, 'objects': page.content}


def document_state(document):
    return {
        'revision': document.revision,
        'pages': [page_state(p) for p in document.pages.order_by('position', 'id')],
    }


class _Batch:
    def __init__(self, document, user, level):
        self.document = document
        self.user = user
        self.level = level
        self.pages = list(document.pages.order_by('position', 'id'))
        self.changed = {}  # id(page) -> page (pages pas encore enregistrées : pas de clé)
        self.created = []
        self.deleted = []

    def page(self, uid):
        for page in self.pages:
            if page.uid == uid:
                return page
        raise OpError('not_found', 'Page introuvable.')

    def need(self, level):
        if LEVELS[self.level] < LEVELS[level]:
            raise OpError('forbidden', 'Action non autorisée.')

    def owns(self, obj):
        if self.level != 'manage' and obj.get('_by') != self.user.pk:
            raise OpError('forbidden', 'Cet objet appartient à quelqu’un d’autre.')

    def renumber(self):
        for index, page in enumerate(self.pages):
            if page.position != index:
                page.position = index
                self.changed[id(page)] = page

    # --- objets ---------------------------------------------------------
    def object_add(self, op, revision):
        self.need('edit')
        page = self.page(_require_id(op.get('page'), 'page'))
        obj = op.get('object')
        if not isinstance(obj, dict):
            raise OpError('invalid', 'Objet manquant.')
        oid = _require_id(obj.get('id'), 'objet')
        if oid in page.content:
            raise OpError('conflict', 'Un objet porte déjà cet identifiant.')
        if len(page.content) >= MAX_OBJECTS_PER_PAGE:
            raise OpError('too_large', 'Trop d’objets sur cette page.')
        obj = {k: v for k, v in obj.items() if not k.startswith('_')}
        _check_object(obj)
        obj.update({'_by': self.user.pk, '_rev': revision})
        page.content[oid] = obj
        self.changed[id(page)] = page
        return {'page': page.uid, 'object': obj}, page.uid, oid

    def object_update(self, op, revision):
        self.need('edit')
        page = self.page(_require_id(op.get('page'), 'page'))
        oid = _require_id(op.get('id'), 'objet')
        current = page.content.get(oid)
        if current is None:
            raise OpError('conflict', 'Objet supprimé entre-temps.')
        self.owns(current)
        props = op.get('props')
        if not isinstance(props, dict) or not props:
            raise OpError('invalid', 'Modifications manquantes.')
        props = {k: v for k, v in props.items() if not k.startswith('_') and k not in ('id', 'type')}
        merged = {**current, **props}
        _check_object({k: v for k, v in merged.items() if not k.startswith('_')})
        stale = isinstance(op.get('base_rev'), int) and current.get('_rev', 0) > op['base_rev']
        merged['_rev'] = revision
        page.content[oid] = merged
        self.changed[id(page)] = page
        return {'page': page.uid, 'id': oid, 'props': props, 'stale': stale}, page.uid, oid

    def object_delete(self, op, revision):
        self.need('edit')
        page = self.page(_require_id(op.get('page'), 'page'))
        oid = _require_id(op.get('id'), 'objet')
        current = page.content.get(oid)
        if current is None:
            raise OpError('conflict', 'Objet déjà supprimé.')
        self.owns(current)
        del page.content[oid]
        self.changed[id(page)] = page
        return {'page': page.uid, 'id': oid}, page.uid, oid

    # --- pages ----------------------------------------------------------
    def page_add(self, op, revision):
        self.need('edit')
        data = op.get('page')
        if not isinstance(data, dict):
            raise OpError('invalid', 'Page manquante.')
        uid = _require_id(data.get('uid'), 'page')
        if any(p.uid == uid for p in self.pages):
            raise OpError('conflict', 'Une page porte déjà cet identifiant.')
        if len(self.pages) >= MAX_PAGES:
            raise OpError('too_large', 'Nombre maximal de pages atteint.')
        background = data.get('background', 'blank')
        if background not in dict(WhiteboardPage.BACKGROUNDS):
            raise OpError('invalid', 'Fond de page invalide.')
        title = str(data.get('title', ''))[:200]
        index = op.get('index', len(self.pages))
        index = max(0, min(len(self.pages), index if isinstance(index, int) else len(self.pages)))
        page = WhiteboardPage(document=self.document, uid=uid, title=title, background=background, content={})
        self.pages.insert(index, page)
        self.created.append(page)
        self.renumber()
        return {'page': {'uid': uid, 'title': title, 'background': background}, 'index': index}, uid, ''

    def page_update(self, op, revision):
        self.need('manage')
        page = self.page(_require_id(op.get('page'), 'page'))
        props = op.get('props')
        if not isinstance(props, dict) or not props or set(props) - PAGE_PROPS:
            raise OpError('invalid', 'Modification de page invalide.')
        if 'background' in props and props['background'] not in dict(WhiteboardPage.BACKGROUNDS):
            raise OpError('invalid', 'Fond de page invalide.')
        if 'title' in props:
            page.title = str(props['title'])[:200]
        if 'background' in props:
            page.background = props['background']
        self.changed[id(page)] = page
        return {'page': page.uid, 'props': {'title': page.title, 'background': page.background}}, page.uid, ''

    def page_move(self, op, revision):
        self.need('manage')
        page = self.page(_require_id(op.get('page'), 'page'))
        index = op.get('index')
        if not isinstance(index, int):
            raise OpError('invalid', 'Position invalide.')
        self.pages.remove(page)
        index = max(0, min(len(self.pages), index))
        self.pages.insert(index, page)
        self.renumber()
        return {'page': page.uid, 'index': index}, page.uid, ''

    def page_delete(self, op, revision):
        self.need('manage')
        page = self.page(_require_id(op.get('page'), 'page'))
        if len(self.pages) <= 1:
            raise OpError('invalid', 'Le document doit garder au moins une page.')
        self.pages.remove(page)
        self.changed.pop(id(page), None)
        if page in self.created:
            self.created.remove(page)
        else:
            self.deleted.append(page)
        self.renumber()
        return {'page': page.uid}, page.uid, ''

    HANDLERS = {
        'object.add': object_add, 'object.update': object_update, 'object.delete': object_delete,
        'page.add': page_add, 'page.update': page_update, 'page.move': page_move, 'page.delete': page_delete,
    }


def apply_operations(document, user, ops, client_id=''):
    """Applique un lot d'opérations. Renvoie {"revision", "results", "accepted"}.

    results : un élément par opération reçue, dans l'ordre :
      {"op_id", "status": "accepted"|"duplicate"|"rejected", "revision"?, "code"?, "message"?}
    accepted : opérations canoniques à diffuser aux autres clients.
    """
    if not isinstance(ops, list) or not ops:
        raise OpError('invalid', 'Aucune opération.')
    if len(ops) > MAX_OPS_PER_BATCH:
        raise OpError('too_large', f'{MAX_OPS_PER_BATCH} opérations au maximum par envoi.')
    client_id = str(client_id or '')[:64]

    with transaction.atomic():
        document = WhiteboardDocument.objects.select_for_update().get(pk=document.pk)
        level = access_level(user, document)
        if LEVELS[level] < LEVELS['edit']:
            raise OpError('forbidden', 'Vous ne pouvez pas modifier ce document.')
        batch = _Batch(document, user, level)
        op_ids = [op.get('op_id') for op in ops if isinstance(op, dict)]
        known = dict(WhiteboardOperation.objects.filter(
            document=document, op_id__in=[i for i in op_ids if isinstance(i, str)],
        ).values_list('op_id', 'revision'))
        results, accepted, records = [], [], []
        revision = document.revision
        for op in ops:
            op_id = op.get('op_id') if isinstance(op, dict) else None
            try:
                op_id = _require_id(op_id, 'opération')
                if op_id in known:
                    results.append({'op_id': op_id, 'status': 'duplicate', 'revision': known[op_id]})
                    continue
                handler = _Batch.HANDLERS.get(op.get('kind'))
                if handler is None:
                    raise OpError('invalid', 'Type d’opération inconnu.')
                payload, page_uid, object_id = handler(batch, op, revision + 1)
            except OpError as exc:
                results.append({'op_id': op_id, 'status': 'rejected', 'code': exc.code, 'message': exc.message})
                continue
            revision += 1
            known[op_id] = revision
            canonical = {'op_id': op_id, 'kind': op['kind'], 'revision': revision,
                         'author': user.pk, 'client_id': client_id, **payload}
            records.append(WhiteboardOperation(
                document=document, revision=revision, op_id=op_id, kind=op['kind'],
                page_uid=page_uid, object_id=object_id, payload=canonical,
                author=user, client_id=client_id))
            accepted.append(canonical)
            results.append({'op_id': op_id, 'status': 'accepted', 'revision': revision})

        if records:
            for page in batch.deleted:
                page.delete()
            for page in batch.created:
                page.save()
            created = {id(p) for p in batch.created}
            for page in batch.changed.values():
                if id(page) not in created:
                    page.save(update_fields=('content', 'title', 'background', 'position', 'updated_at'))
            WhiteboardOperation.objects.bulk_create(records)
            document.revision = revision
            document.save(update_fields=('revision', 'updated_at'))
            _maybe_auto_snapshot(document)
    return {'revision': document.revision, 'results': results, 'accepted': accepted}


def operations_since(document, since, limit=500):
    """Opérations après la révision `since` ; reset=True si le client doit tout recharger."""
    if since < 0 or since > document.revision:
        return {'reset': True, 'revision': document.revision, 'ops': []}
    ops = list(document.operations.filter(revision__gt=since).order_by('revision')
               .values_list('payload', flat=True)[:limit + 1])
    if len(ops) > limit or (ops and ops[0].get('revision') != since + 1) \
            or (not ops and since != document.revision):
        return {'reset': True, 'revision': document.revision, 'ops': []}
    if any(op.get('kind') == 'document.restore' for op in ops):
        return {'reset': True, 'revision': document.revision, 'ops': []}
    return {'reset': False, 'revision': document.revision, 'ops': ops}


def create_snapshot(document, kind=WhiteboardSnapshot.KIND_MANUAL, user=None, label=''):
    return WhiteboardSnapshot.objects.create(
        document=document, revision=document.revision, kind=kind,
        label=str(label)[:200], data=document_state(document), created_by=user)


AUTO_SNAPSHOT_MINUTES = 10           # ou toutes les 10 minutes d'activité
AUTO_SNAPSHOT_MIN_OPS = 20


def _maybe_auto_snapshot(document):
    from datetime import timedelta
    last = document.snapshots.order_by('-revision').values('revision', 'created_at').first()
    last_revision = last['revision'] if last else 0
    done = document.revision - last_revision
    old = last is None or last['created_at'] < timezone.now() - timedelta(minutes=AUTO_SNAPSHOT_MINUTES)
    if done < AUTO_SNAPSHOT_EVERY and not (old and done >= AUTO_SNAPSHOT_MIN_OPS):
        return
    create_snapshot(document, WhiteboardSnapshot.KIND_AUTO)
    stale = list(document.snapshots.filter(kind=WhiteboardSnapshot.KIND_AUTO)
                 .order_by('-revision').values_list('pk', flat=True)[AUTO_SNAPSHOT_KEEP:])
    if stale:
        WhiteboardSnapshot.objects.filter(pk__in=stale).delete()


def restore_snapshot(document, snapshot, user):
    """Remplace l'état par une version. L'état actuel est d'abord sauvegardé."""
    with transaction.atomic():
        document = WhiteboardDocument.objects.select_for_update().get(pk=document.pk)
        create_snapshot(document, WhiteboardSnapshot.KIND_BEFORE_RESTORE, user,
                        f'Avant restauration de la révision {snapshot.revision}')
        document.pages.all().delete()
        pages = snapshot.data.get('pages') or []
        for index, page in enumerate(pages):
            WhiteboardPage.objects.create(
                document=document, uid=page['uid'], position=index, title=page.get('title', ''),
                background=page.get('background', 'blank'), content=page.get('objects') or {})
        if not pages:
            WhiteboardPage.objects.create(document=document, uid='page-1', position=0)
        document.revision += 1
        stamp = timezone.now().strftime('%Y%m%d%H%M%S%f')
        payload = {'op_id': f'restore-{snapshot.pk}-{stamp}', 'kind': 'document.restore',
                   'revision': document.revision, 'author': user.pk, 'snapshot': snapshot.pk,
                   'snapshot_revision': snapshot.revision}
        WhiteboardOperation.objects.create(
            document=document, revision=document.revision, op_id=payload['op_id'],
            kind='document.restore', payload=payload, author=user)
        document.save(update_fields=('revision', 'updated_at'))
    return document, payload
