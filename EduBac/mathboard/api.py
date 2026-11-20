"""API REST du tableau mathématique (Django REST Framework).

Toutes les réponses sont en JSON ; les messages d'erreur sont en français.
"""
from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from . import notify, realtime
from .access import access_level, can, can_invite, can_share_with_classroom, visible_documents
from .models import WhiteboardDocument, WhiteboardMember, WhiteboardPage, WhiteboardSnapshot
from .operations import (
    OpError, apply_operations, create_snapshot, document_state, operations_since, restore_snapshot,
)
from .serializers import DocumentSerializer, MemberSerializer, SnapshotSerializer, presentation_data

User = get_user_model()


def _document(request, pk, needed='view'):
    document = get_object_or_404(WhiteboardDocument.objects.select_related('classroom', 'owner', 'source__classroom'), pk=pk)
    level = access_level(request.user, document)
    if level is None:
        raise NotFound('Document introuvable.')  # ne pas révéler son existence
    if not can(request.user, document, needed):
        raise PermissionDenied('Action non autorisée sur ce document.')
    return document, level


def _check_classroom(user, data):
    classroom = data.get('classroom')
    if classroom is not None and not can_share_with_classroom(user, classroom):
        raise PermissionDenied('Vous ne pouvez partager qu’avec vos propres classes.')


class DocumentListView(APIView):
    def get(self, request):
        qs = visible_documents(request.user)
        if request.query_params.get('archives') != '1':
            qs = qs.filter(is_archived=False)
        documents = list(qs[:200])
        levels = {d.pk: access_level(request.user, d) for d in documents}
        return Response(DocumentSerializer(documents, many=True, context={'levels': levels}).data)

    def post(self, request):
        serializer = DocumentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        _check_classroom(request.user, serializer.validated_data)
        with transaction.atomic():
            document = serializer.save(owner=request.user)
            WhiteboardPage.objects.create(document=document, uid='page-1', position=0)
        if document.classroom_id and document.class_visible:
            notify.classroom_shared(document, request.user)
        return Response(DocumentSerializer(document, context={'levels': {document.pk: 'manage'}}).data,
                        status=status.HTTP_201_CREATED)


class DocumentDetailView(APIView):
    def get(self, request, pk):
        document, level = _document(request, pk)
        return Response(DocumentSerializer(document, context={'levels': {document.pk: level}}).data)

    def patch(self, request, pk):
        document, level = _document(request, pk, 'manage')
        serializer = DocumentSerializer(document, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        if 'classroom' in serializer.validated_data:
            _check_classroom(request.user, serializer.validated_data)
        before = (document.classroom_id, document.accepts_submissions, document.class_visible)
        document = serializer.save()
        newly_assigned = document.accepts_submissions and not before[1]
        newly_visible = document.class_visible and not before[2]
        if document.classroom_id and document.class_visible and (
                document.classroom_id != before[0] or newly_assigned or newly_visible):
            # Nouvelle classe, document enfin partagé ou devenu un travail à rendre :
            # les élèves sont prévenus. Tant qu'il est « préparé », rien n'est envoyé.
            notify.classroom_shared(document, request.user)
        realtime.publish(document.pk, {'type': 'document', 'document': DocumentSerializer(document).data})
        return Response(DocumentSerializer(document, context={'levels': {document.pk: level}}).data)

    def delete(self, request, pk):
        document, _ = _document(request, pk, 'manage')
        if document.owner_id != request.user.pk and not (request.user.is_staff or request.user.is_superuser):
            raise PermissionDenied('Seul le propriétaire peut supprimer ce document.')
        document.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class DocumentStateView(APIView):
    def get(self, request, pk):
        document, level = _document(request, pk)
        state = document_state(document)
        state.update({'document': DocumentSerializer(document, context={'levels': {document.pk: level}}).data,
                      'access': level, 'me': request.user.pk})
        return Response(state)


class OperationsView(APIView):
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = 'mathboard_ops'

    def get(self, request, pk):
        document, level = _document(request, pk)
        try:
            since = int(request.query_params.get('since', ''))
        except ValueError:
            raise ValidationError({'since': 'Révision attendue.'})
        # La présentation en cours et l'empreinte des réglages accompagnent le
        # rattrapage : sans WebSocket, le client voit ainsi un changement de droits.
        settings_key = '|'.join(str(v) for v in (
            level, document.submission_status, document.classroom_id, document.students_can_edit, document.class_visible,
            document.accepts_submissions, document.grade, document.returned_at))
        return Response({**operations_since(document, since), 'presentation': presentation_data(document),
                         'settings': settings_key})

    def post(self, request, pk):
        document, _ = _document(request, pk, 'edit')
        try:
            result = apply_operations(document, request.user, request.data.get('ops'),
                                      request.data.get('client_id', ''))
        except OpError as exc:
            if exc.code == 'forbidden':
                raise PermissionDenied(exc.message)
            raise ValidationError({'detail': exc.message, 'code': exc.code})
        if result['accepted']:
            realtime.publish(document.pk, {'type': 'ops', 'revision': result['revision'],
                                           'ops': result['accepted']})
        return Response({'revision': result['revision'], 'results': result['results']})


class MemberListView(APIView):
    def get(self, request, pk):
        document, _ = _document(request, pk, 'manage')
        members = document.members.select_related('user').order_by('user__last_name', 'user__username')
        return Response(MemberSerializer(members, many=True).data)

    def post(self, request, pk):
        document, _ = _document(request, pk, 'manage')
        if document.submission_status:
            raise ValidationError({'user': 'Une copie d’élève ne se partage pas.'})
        role = request.data.get('role', WhiteboardMember.ROLE_VIEWER)
        if role not in dict(WhiteboardMember.ROLES):
            raise ValidationError({'role': 'Rôle invalide.'})
        target = User.objects.filter(pk=request.data.get('user')).first() if str(
            request.data.get('user', '')).isdigit() else User.objects.filter(
            username__iexact=str(request.data.get('username', '')).strip()).first()
        if target is None or not can_invite(request.user, target):
            raise ValidationError({'user': 'Utilisateur introuvable ou non autorisé.'})
        if target.pk == document.owner_id:
            raise ValidationError({'user': 'Le propriétaire a déjà tous les droits.'})
        member, created = WhiteboardMember.objects.update_or_create(
            document=document, user=target, defaults={'role': role, 'added_by': request.user})
        if created:
            notify.member_invited(member, request.user)
        return Response(MemberSerializer(member).data,
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class MemberDetailView(APIView):
    def _member(self, request, pk, member_id):
        document, _ = _document(request, pk, 'manage')
        return get_object_or_404(WhiteboardMember, pk=member_id, document=document)

    def patch(self, request, pk, member_id):
        member = self._member(request, pk, member_id)
        role = request.data.get('role')
        if role not in dict(WhiteboardMember.ROLES):
            raise ValidationError({'role': 'Rôle invalide.'})
        member.role = role
        member.save(update_fields=('role',))
        return Response(MemberSerializer(member).data)

    def delete(self, request, pk, member_id):
        self._member(request, pk, member_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class SnapshotListView(APIView):
    def get(self, request, pk):
        document, _ = _document(request, pk)
        return Response(SnapshotSerializer(document.snapshots.select_related('created_by')[:100], many=True).data)

    def post(self, request, pk):
        document, _ = _document(request, pk, 'edit')
        snapshot = create_snapshot(document, WhiteboardSnapshot.KIND_MANUAL, request.user,
                                   request.data.get('label', ''))
        return Response(SnapshotSerializer(snapshot).data, status=status.HTTP_201_CREATED)


class SnapshotDetailView(APIView):
    def get(self, request, pk, snapshot_id):
        document, _ = _document(request, pk)
        snapshot = get_object_or_404(WhiteboardSnapshot, pk=snapshot_id, document=document)
        return Response({**SnapshotSerializer(snapshot).data, 'data': snapshot.data})


class SnapshotRestoreView(APIView):
    def post(self, request, pk, snapshot_id):
        document, _ = _document(request, pk, 'manage')
        snapshot = get_object_or_404(WhiteboardSnapshot, pk=snapshot_id, document=document)
        document, op = restore_snapshot(document, snapshot, request.user)
        realtime.publish(document.pk, {'type': 'ops', 'revision': document.revision, 'ops': [op]})
        return Response({'revision': document.revision})


# --- Phase 3 : calcul symbolique (SymPy) ---------------------------------------

class CalculView(APIView):
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = 'mathboard_calc'

    def post(self, request):
        from edubac_math import ACTION_LABELS, ParseError, compute, latex_to_text
        data = request.data if isinstance(request.data, dict) else {}
        action = data.get('action')
        if action not in ACTION_LABELS:
            raise ValidationError({'detail': 'Opération inconnue.'})
        try:
            expression = latex_to_text(data['latex']) if data.get('latex') else str(data.get('expression', ''))
            other = latex_to_text(data['other_latex']) if data.get('other_latex') else data.get('other')
        except ParseError as exc:
            return Response({'ok': False, 'error': str(exc)})
        options = {k: data.get(k) for k in ('variable', 'order', 'lower', 'upper', 'point', 'direction', 'name')}
        result = compute(action, expression, other=other, **options)
        result.update({'action': action, 'action_label': ACTION_LABELS[action], 'expression': expression})
        return Response(result)


# --- Phase 5 : présence (repli HTTP quand WebSocket est indisponible) ----------

def _color(user_id):
    palette = ('#d9480f', '#1971c2', '#2f9e44', '#9c36b5', '#e8590c', '#0c8599', '#c2255c', '#5f3dc4')
    return palette[user_id % len(palette)]


def presence_list(document):
    from datetime import timedelta
    from django.utils import timezone
    from .models import WhiteboardSession
    limit = timezone.now() - timedelta(seconds=30)
    WhiteboardSession.objects.filter(document=document, last_seen__lt=timezone.now() - timedelta(minutes=2)).delete()
    sessions = WhiteboardSession.objects.filter(document=document, last_seen__gte=limit).select_related('user')
    return [{'client_id': s.client_id, 'user': s.user_id, 'name': s.user.get_full_name() or s.user.username,
             'color': _color(s.user_id), 'page': s.page_uid, 'cursor': s.cursor} for s in sessions]


class PresenceView(APIView):
    def get(self, request, pk):
        document, _ = _document(request, pk)
        return Response(presence_list(document))

    def post(self, request, pk):
        from .models import WhiteboardSession
        document, _ = _document(request, pk)
        client_id = str(request.data.get('client_id', ''))[:64]
        if not client_id:
            raise ValidationError({'client_id': 'Identifiant de connexion manquant.'})
        cursor = request.data.get('cursor')
        if not (isinstance(cursor, dict) and all(isinstance(cursor.get(k), (int, float)) for k in ('x', 'y'))):
            cursor = {}
        else:
            cursor = {'x': float(cursor['x']), 'y': float(cursor['y'])}
        session = WhiteboardSession.objects.filter(document=document, client_id=client_id).first()
        if session and session.user_id != request.user.pk:
            raise PermissionDenied('Session invalide.')
        if session is None:
            session = WhiteboardSession(document=document, client_id=client_id, user=request.user)
        session.page_uid = str(request.data.get('page', ''))[:64]
        session.cursor = cursor
        session.save()
        return Response(presence_list(document))

    def delete(self, request, pk):
        from .models import WhiteboardSession
        document, _ = _document(request, pk)
        WhiteboardSession.objects.filter(document=document, user=request.user,
                                         client_id=str(request.query_params.get('client_id', ''))[:64]).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- Phase 8 : export / import ----------------------------------------------------

EXPORT_FORMAT = 'edubac-mathboard'


class ExportView(APIView):
    def get(self, request, pk):
        from django.utils.text import slugify
        document, _ = _document(request, pk)
        state = document_state(document)
        pages = [{**page, 'objects': {oid: {k: v for k, v in obj.items() if not k.startswith('_')}
                                      for oid, obj in page['objects'].items()}} for page in state['pages']]
        payload = {'format': EXPORT_FORMAT, 'version': 1, 'title': document.title, 'level': document.level,
                   'chapter': document.chapter, 'pages': pages}
        response = Response(payload)
        name = slugify(document.title) or 'tableau'
        response['Content-Disposition'] = f'attachment; filename="{name}.edubac.json"'
        return response


class ImportView(APIView):
    def post(self, request):
        from .operations import MAX_OBJECTS_PER_PAGE, MAX_PAGES, OpError, _check_object, _require_id
        data = request.data.get('data') if isinstance(request.data, dict) else None
        if not isinstance(data, dict) or data.get('format') != EXPORT_FORMAT:
            raise ValidationError({'detail': 'Fichier non reconnu : exportez d’abord un tableau EduBac.'})
        pages = data.get('pages')
        if not isinstance(pages, list) or not pages or len(pages) > MAX_PAGES:
            raise ValidationError({'detail': 'Le fichier ne contient aucune page valide.'})
        clean_pages = []
        try:
            for index, page in enumerate(pages):
                objects = page.get('objects') if isinstance(page, dict) else None
                if not isinstance(objects, dict) or len(objects) > MAX_OBJECTS_PER_PAGE:
                    raise OpError('invalid', f'Page {index + 1} invalide.')
                clean = {}
                for oid, obj in objects.items():
                    _require_id(oid, 'objet')
                    if not isinstance(obj, dict):
                        raise OpError('invalid', 'Objet invalide.')
                    obj = {k: v for k, v in obj.items() if not k.startswith('_')}
                    obj['id'] = oid
                    _check_object(obj)
                    clean[oid] = {**obj, '_by': request.user.pk, '_rev': 0}
                background = page.get('background', 'blank')
                if background not in dict(WhiteboardPage.BACKGROUNDS):
                    background = 'blank'
                clean_pages.append({'title': str(page.get('title', ''))[:200], 'background': background,
                                    'objects': clean})
        except OpError as exc:
            raise ValidationError({'detail': exc.message})
        title = ' '.join(str(data.get('title') or 'Tableau importé').split())[:200] or 'Tableau importé'
        with transaction.atomic():
            document = WhiteboardDocument.objects.create(
                title=title, owner=request.user, level=str(data.get('level', ''))[:50],
                chapter=str(data.get('chapter', ''))[:200])
            for index, page in enumerate(clean_pages):
                WhiteboardPage.objects.create(document=document, uid=f'page-{index + 1}', position=index,
                                              title=page['title'], background=page['background'],
                                              content=page['objects'])
        return Response(DocumentSerializer(document, context={'levels': {document.pk: 'manage'}}).data,
                        status=status.HTTP_201_CREATED)


# --- Phase 7 : assistant IA (service FastAPI indépendant) --------------------------

class AssistantView(APIView):
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = 'mathboard_ai'

    def post(self, request, pk, action):
        from django.conf import settings
        from .ai_client import AIServiceError, call_ai_service
        if not settings.MATHBOARD_AI_ENABLED:
            raise NotFound('Assistant désactivé.')
        document, _ = _document(request, pk)
        try:
            result = call_ai_service(action, document, request.user, request.data)
        except AIServiceError as exc:
            return Response({'detail': exc.message}, status=exc.status)
        return Response(result)
