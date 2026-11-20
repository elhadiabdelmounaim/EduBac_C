"""API du tableau mathématique pour la classe : travail à rendre et correction,
mode présentation (« suivez-moi »), participation par élève, images en fichiers."""
import io
import math
import re
import time

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Count, Max
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from . import notify, realtime
from .access import is_corrector
from .api import _document
from .images import save_image
from .models import WhiteboardDocument, WhiteboardPage, WhiteboardSnapshot
from .operations import create_snapshot
from .serializers import DocumentSerializer, presentation_data

User = get_user_model()
ID_RE = re.compile(r'^[A-Za-z0-9_\-:.]{1,64}$')


def _name(user):
    return user.get_full_name() or user.username


def _publish_document(document):
    """Réglages ou état du travail modifiés : chaque client revérifie ses droits."""
    realtime.publish(document.pk, {'type': 'document', 'document': DocumentSerializer(document).data})


def _correctors(subject):
    people = {}
    if subject is None:
        return []
    people[subject.owner_id] = subject.owner
    if subject.classroom_id and subject.classroom.teacher_id:
        people[subject.classroom.teacher_id] = subject.classroom.teacher
    return [u for u in people.values() if u.is_active]


# --- Travail à rendre ---------------------------------------------------------

class CopyView(APIView):
    """L'élève ouvre (ou crée) sa copie d'un sujet."""

    def post(self, request, pk):
        subject, level = _document(request, pk)
        if subject.submission_status or not subject.accepts_submissions:
            raise ValidationError({'detail': 'Ce document n’est pas un travail à rendre.'})
        if level == 'manage':
            raise ValidationError({'detail': 'Vous êtes responsable de ce sujet : les élèves en font leur copie.'})
        copy = WhiteboardDocument.objects.filter(source=subject, owner=request.user).first()
        created = False
        if copy is None:
            try:
                with transaction.atomic():
                    copy = WhiteboardDocument.objects.create(
                        title=subject.title, owner=request.user, source=subject, lesson=subject.lesson,
                        level=subject.level, chapter=subject.chapter,
                        submission_status=WhiteboardDocument.STATUS_DRAFT)
                    for page in subject.pages.order_by('position', 'id'):
                        WhiteboardPage.objects.create(document=copy, uid=page.uid, position=page.position,
                                                      title=page.title, background=page.background,
                                                      content=page.content)
                    created = True
            except IntegrityError:  # double clic : la copie existe déjà
                copy = WhiteboardDocument.objects.get(source=subject, owner=request.user)
        from .access import access_level
        data = DocumentSerializer(copy, context={'levels': {copy.pk: access_level(request.user, copy)}}).data
        return Response(data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class SubmitView(APIView):
    def post(self, request, pk):
        copy, _ = _document(request, pk)
        if not copy.submission_status or copy.owner_id != request.user.pk:
            raise PermissionDenied('Seul l’élève qui a fait ce travail peut le rendre.')
        if copy.submission_status != WhiteboardDocument.STATUS_DRAFT:
            raise ValidationError({'detail': 'Ce travail a déjà été rendu.'})
        copy.submission_status = WhiteboardDocument.STATUS_SUBMITTED
        copy.submitted_at = timezone.now()
        copy.save(update_fields=('submission_status', 'submitted_at', 'updated_at'))
        create_snapshot(copy, WhiteboardSnapshot.KIND_MANUAL, request.user, 'Travail rendu')
        notify.copy_submitted(copy, _correctors(copy.source))
        _publish_document(copy)
        return Response(DocumentSerializer(copy, context={'levels': {copy.pk: 'view'}}).data)


class CorrectView(APIView):
    """Le professeur rend la copie corrigée, ou demande à l'élève de la reprendre."""

    def post(self, request, pk):
        copy, level = _document(request, pk)
        if not copy.submission_status or not is_corrector(request.user, copy.source) or level != 'manage':
            raise PermissionDenied('Seul le professeur du sujet corrige ce travail.')
        if copy.submission_status == WhiteboardDocument.STATUS_DRAFT:
            raise ValidationError({'detail': 'Ce travail n’a pas encore été rendu.'})
        action = request.data.get('action', 'return')
        if action not in ('return', 'redo'):
            raise ValidationError({'action': 'Action inconnue.'})
        copy.grade = ' '.join(str(request.data.get('grade', copy.grade) or '').split())[:20]
        copy.feedback = str(request.data.get('feedback', copy.feedback) or '').strip()[:4000]
        redo = action == 'redo'
        copy.submission_status = WhiteboardDocument.STATUS_DRAFT if redo else WhiteboardDocument.STATUS_RETURNED
        copy.returned_at = timezone.now()
        copy.save(update_fields=('grade', 'feedback', 'submission_status', 'returned_at', 'updated_at'))
        create_snapshot(copy, WhiteboardSnapshot.KIND_MANUAL, request.user,
                        'Reprise demandée' if redo else 'Correction rendue')
        notify.copy_returned(copy, request.user, redo)
        _publish_document(copy)
        return Response(DocumentSerializer(copy, context={'levels': {copy.pk: 'manage'}}).data)


class CopiesView(APIView):
    """Suivi des copies d'un sujet : chaque élève de la classe et l'état de son travail."""

    def get(self, request, pk):
        subject, _ = _document(request, pk, 'manage')
        copies = {c.owner_id: c for c in subject.copies.select_related('owner')}
        students = []
        if subject.classroom_id:
            students = [m.user for m in subject.classroom.members.select_related('user') if m.user.is_active]
        known = {u.pk for u in students}
        students += [c.owner for c in copies.values() if c.owner_id not in known]
        rows = []
        for student in sorted(students, key=lambda u: (u.last_name.lower(), u.first_name.lower(), u.username)):
            copy = copies.get(student.pk)
            handed_in = copy is not None and copy.submission_status != WhiteboardDocument.STATUS_DRAFT
            rows.append({
                'student': student.pk, 'name': _name(student),
                'status': copy.submission_status if copy else 'none',
                'copy': copy.pk if handed_in else None,
                'submitted_at': copy.submitted_at if copy else None,
                'grade': copy.grade if handed_in else '',
            })
        return Response({'accepts_submissions': subject.accepts_submissions, 'due_at': subject.due_at,
                         'rows': rows})


# --- Mode présentation ---------------------------------------------------------

def _number(value, low, high):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValidationError({'detail': 'Vue invalide.'})
    if not math.isfinite(number) or not low <= number <= high:
        raise ValidationError({'detail': 'Vue invalide.'})
    return round(number, 2)


class PresentationView(APIView):
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = 'mathboard_ops'

    def post(self, request, pk):
        document, _ = _document(request, pk, 'manage')
        page = str(request.data.get('page', ''))
        if not ID_RE.match(page) or not document.pages.filter(uid=page).exists():
            raise ValidationError({'detail': 'Page introuvable.'})
        view = {'page': page, 'cx': _number(request.data.get('cx'), -1e6, 1e6),
                'cy': _number(request.data.get('cy'), -1e6, 1e6),
                'w': _number(request.data.get('w'), 10, 1e6), 'h': _number(request.data.get('h'), 10, 1e6),
                'at': round(time.time(), 1)}
        # update() : la présentation ne change ni la date de modification ni la révision.
        WhiteboardDocument.objects.filter(pk=document.pk).update(presenter=request.user, presentation=view)
        document.presenter, document.presenter_id, document.presentation = request.user, request.user.pk, view
        data = presentation_data(document)
        realtime.publish(document.pk, {'type': 'presentation', 'presentation': data})
        return Response(data)

    def delete(self, request, pk):
        document, _ = _document(request, pk, 'manage')
        WhiteboardDocument.objects.filter(pk=document.pk).update(presenter=None, presentation={})
        realtime.publish(document.pk, {'type': 'presentation', 'presentation': None})
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- Participation par élève -----------------------------------------------------

class ContributionsView(APIView):
    def get(self, request, pk):
        document, _ = _document(request, pk, 'manage')
        counts = {}
        for page in document.pages.all():
            for obj in page.content.values():
                author = obj.get('_by')
                if isinstance(author, int):
                    entry = counts.setdefault(author, {'objects': 0, 'pages': set()})
                    entry['objects'] += 1
                    entry['pages'].add(page.uid)
        activity = {row['author']: row for row in document.operations.exclude(author=None)
                    .values('author').annotate(last=Max('created_at'), ops=Count('id'))}
        ids = set(counts) | set(activity)
        users = {u.pk: u for u in User.objects.filter(pk__in=ids)}
        rows = []
        for user_id in ids:
            user = users.get(user_id)
            if user is None:
                continue
            rows.append({
                'user': user_id, 'name': _name(user), 'is_owner': user_id == document.owner_id,
                'role': 'Professeur' if user.is_teacher() else ('Élève' if user.is_student() else 'Administration'),
                'objects': counts.get(user_id, {}).get('objects', 0),
                'pages': sorted(counts.get(user_id, {}).get('pages', ())),
                'operations': activity.get(user_id, {}).get('ops', 0),
                'last_activity': activity.get(user_id, {}).get('last'),
            })
        rows.sort(key=lambda r: (not r['is_owner'], -r['objects'], r['name'].lower()))
        return Response(rows)


# --- Images enregistrées comme fichiers (et non dans la base) ---------------------

MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_IMAGE_SIDE = 1600
FORMATS = {'PNG': ('png', 'PNG'), 'JPEG': ('jpg', 'JPEG'), 'WEBP': ('webp', 'WEBP')}


class ImageUploadView(APIView):
    parser_classes = (MultiPartParser,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = 'mathboard_upload'

    def post(self, request, pk):
        from PIL import Image, UnidentifiedImageError
        document, _ = _document(request, pk, 'edit')
        upload = request.FILES.get('image')
        if upload is None:
            raise ValidationError({'detail': 'Aucune image reçue.'})
        if upload.size > MAX_UPLOAD_BYTES:
            raise ValidationError({'detail': 'Image trop lourde (8 Mo au maximum).'})
        try:
            image = Image.open(upload)
            kind = image.format
            if kind not in FORMATS:
                raise ValidationError({'detail': 'Formats acceptés : PNG, JPEG, WebP.'})
            image.load()
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
            raise ValidationError({'detail': 'Image illisible.'})
        image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
        if kind == 'JPEG' and image.mode not in ('RGB', 'L'):
            image = image.convert('RGB')
        # Ré-encodage : supprime les métadonnées (position GPS…) et tout contenu caché.
        out = io.BytesIO()
        extension, pil_format = FORMATS[kind]
        image.save(out, pil_format, **({'quality': 85} if pil_format in ('JPEG', 'WEBP') else {'optimize': True}))
        src = save_image(document.pk, out.getvalue(), extension)
        return Response({'src': src, 'width': image.width, 'height': image.height},
                        status=status.HTTP_201_CREATED)


class RecognitionView(APIView):
    """Tracés manuscrits → texte ou formule LaTeX (moteur spécialisé, sans IA générative)."""
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = 'mathboard_recognition'

    def post(self, request, pk):
        from django.http import Http404
        from . import recognition
        if not recognition.enabled():
            raise Http404('Reconnaissance de l’écriture non configurée.')
        _document(request, pk, 'edit')
        try:
            kind, lang, strokes, width, height = recognition.clean_request(request.data)
            result = recognition.recognize(kind, lang, strokes, width, height)
        except recognition.RecognitionError as exc:
            raise ValidationError({'detail': str(exc)})
        return Response({'latex': result} if kind == 'math' else {'text': result})
