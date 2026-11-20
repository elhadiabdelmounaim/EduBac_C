"""Pages du tableau mathématique (liste et éditeur)."""
from django.conf import settings
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.csrf import ensure_csrf_cookie

from accounts.decorators import login_required_simple
from accounts.models import StudentProfile

from .access import access_level, visible_documents
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
    documents = list(visible_documents(user).filter(is_archived=False)[:200])
    for document in documents:
        document.my_access = access_level(user, document)
    return render(request, 'mathboard/list.html', {
        'page_title': 'Tableau mathématique',
        'documents': documents,
        'classrooms': _classrooms(user),
        'levels': StudentProfile.NIVEAU_CHOICES,
    })


@login_required_simple
@ensure_csrf_cookie
def document_editor(request, pk):
    user = request.edubac_user
    document = get_object_or_404(WhiteboardDocument.objects.select_related('classroom'), pk=pk)
    level = access_level(user, document)
    if level is None:
        raise Http404('Document introuvable.')
    config = {
        'id': document.pk,
        'me': user.pk,
        'access': level,
        'isTeacher': user.is_teacher(),
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
        },
    }
    return render(request, 'mathboard/editor.html', {
        'page_title': document.title,
        'document': document,
        'config': config,
    })
