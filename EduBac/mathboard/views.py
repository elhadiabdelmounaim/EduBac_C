"""Pages du tableau mathématique (liste et éditeur)."""
from django.conf import settings
from django.contrib import messages
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from accounts.decorators import login_required_simple
from accounts.models import StudentProfile

from .access import access_level, is_corrector, visible_documents
from .api_class import handwriting_allowed
from .models import WhiteboardDocument


def _classrooms(user):
    if user.is_staff or user.is_superuser:
        from classrooms.models import Classroom
        return Classroom.objects.filter(is_active=True)
    return user.managed_classrooms.filter(is_active=True) if user.is_teacher() else []


@login_required_simple
@ensure_csrf_cookie
def document_list(request):
    user = request.edubac_user
    visible = visible_documents(user).filter(is_archived=False)
    documents = list(visible.filter(submission_status='')[:200])
    for document in documents:
        document.my_access = access_level(user, document)
    my_work = list(visible.filter(owner=user).exclude(submission_status='').order_by('-updated_at')[:100])
    to_grade = list(visible.exclude(owner=user).filter(submission_status=WhiteboardDocument.STATUS_SUBMITTED)
                    .select_related('owner', 'source').order_by('submitted_at')[:200])
    return render(request, 'mathboard/list.html', {
        'page_title': 'Tableau mathématique',
        'documents': documents,
        'my_work': my_work,
        'to_grade': to_grade,
        'classrooms': _classrooms(user),
        'levels': StudentProfile.NIVEAU_CHOICES,
    })


@login_required_simple
@ensure_csrf_cookie
def document_editor(request, pk):
    user = request.edubac_user
    document = get_object_or_404(WhiteboardDocument.objects.select_related('classroom', 'source__classroom', 'owner'), pk=pk)
    level = access_level(user, document)
    if level is None:
        raise Http404('Document introuvable.')
    my_copy = None
    if document.accepts_submissions and not document.submission_status and level != 'manage':
        my_copy = WhiteboardDocument.objects.filter(source=document, owner=user).values_list('pk', flat=True).first()
    config = {
        'id': document.pk,
        'me': user.pk,
        'access': level,
        'isTeacher': user.is_teacher(),
        'aiEnabled': settings.MATHBOARD_AI_ENABLED,
        # Conversion de l'écriture : enseignants et administrateurs (service payant).
        'handwriting': handwriting_allowed(user),
        # Travail à rendre : copie de l'élève, ou sujet dont l'élève peut faire une copie.
        'isCopy': bool(document.submission_status),
        'isCorrector': bool(document.submission_status) and is_corrector(user, document.source),
        'isOwner': document.owner_id == user.pk,
        'myCopy': reverse('mathboard:editor', args=[my_copy]) if my_copy else '',
        'subject': ({'id': document.source_id, 'title': document.source.title,
                     'url': reverse('mathboard:editor', args=[document.source_id])}
                    if document.source_id and access_level(user, document.source) else None),
        # WebSocket seulement sur un serveur ASGI (sinon : interrogation HTTP).
        'wsPath': f'/ws/tableau-maths/{document.pk}/' if settings.MATHBOARD_WEBSOCKET else '',
        'classrooms': [{'id': c.pk, 'name': c.name} for c in _classrooms(user)],
        'levels': [{'code': code, 'label': label} for code, label in StudentProfile.NIVEAU_CHOICES],
        'urls': {
            'list': reverse('mathboard:list'),
            'state': reverse('mathboard:api_state', args=[document.pk]),
            'ops': reverse('mathboard:api_operations', args=[document.pk]),
            'document': reverse('mathboard:api_document', args=[document.pk]),
            'presence': reverse('mathboard:api_presence', args=[document.pk]),
            'members': reverse('mathboard:api_members', args=[document.pk]),
            'snapshots': reverse('mathboard:api_snapshots', args=[document.pk]),
            'export': reverse('mathboard:api_export', args=[document.pk]),
            'calc': reverse('mathboard:api_calcul'),
            'ai': reverse('mathboard:api_ai', args=[document.pk, 'ACTION']),
            'copy': reverse('mathboard:api_copy', args=[document.pk]),
            'submit': reverse('mathboard:api_submit', args=[document.pk]),
            'correct': reverse('mathboard:api_correct', args=[document.pk]),
            'copies': reverse('mathboard:api_copies', args=[document.pk]),
            'presentation': reverse('mathboard:api_presentation', args=[document.pk]),
            'contributions': reverse('mathboard:api_contributions', args=[document.pk]),
            'images': reverse('mathboard:api_images', args=[document.pk]),
            'handwriting': reverse('mathboard:api_handwriting', args=[document.pk]),
            'editor': reverse('mathboard:editor', args=[0]),
        },
    }
    return render(request, 'mathboard/editor.html', {
        'page_title': document.title,
        'document': document,
        'config': config,
    })


@login_required_simple
@require_POST
def convert_legacy(request, board_id):
    """Copie un tableau de l'ancien module dans le tableau mathématique."""
    from whiteboard.models import WhiteboardBoard
    from .legacy import convert_board
    user = request.edubac_user
    board = get_object_or_404(WhiteboardBoard, pk=board_id, is_active=True)
    if board.created_by_id != user.pk and not (user.is_staff or user.is_superuser):
        raise Http404('Tableau introuvable.')
    existing = WhiteboardDocument.objects.filter(legacy_board=board, owner=user).first()
    if existing:
        messages.info(request, 'Ce tableau a déjà été converti : voici sa copie.')
        return redirect('mathboard:editor', existing.pk)
    document, report = convert_board(board, user)
    skipped = sum(report['skipped'].values())
    text = f'Tableau converti : {report["converted"]} élément(s).'
    if skipped:
        details = ', '.join(f'{n} {kind}' for kind, n in sorted(report['skipped'].items()))
        text += f' Non repris : {details}.'
    messages.success(request, text)
    return redirect('mathboard:editor', document.pk)


@login_required_simple
def image(request, pk, filename):
    """Image d'un tableau, visible par qui peut ouvrir ce tableau.

    Une copie d'élève reprend les images du sujet : son propriétaire les voit
    même si le sujet ne lui est plus accessible.
    """
    from django.core.files.storage import default_storage
    from .images import CONTENT_TYPES, FILENAME
    match = FILENAME.match(filename)
    if not match:
        raise Http404('Image introuvable.')
    user = request.edubac_user
    document = get_object_or_404(WhiteboardDocument.objects.select_related('classroom', 'source__classroom'), pk=pk)
    if not access_level(user, document) and not WhiteboardDocument.objects.filter(source=document, owner=user).exists():
        raise Http404('Image introuvable.')
    name = f'mathboard/{pk}/{filename}'
    if not default_storage.exists(name):
        raise Http404('Image introuvable.')
    response = FileResponse(default_storage.open(name, 'rb'), content_type=CONTENT_TYPES[match.group(1)])
    # Nom aléatoire et contenu jamais modifié : cache long, mais privé (contrôle d'accès).
    response['Cache-Control'] = 'private, max-age=604800, immutable'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
