"""Partage d'une image PNG de whiteboard vers une seule classe."""
import io
import logging
import uuid

from django.core.files.base import ContentFile
from django.http import FileResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST
from PIL import Image, UnidentifiedImageError

from accounts.decorators import login_required_simple
from classrooms.models import Classroom

from .models import WhiteboardShare
from .permissions import user_can_access_classroom, user_can_view_share, visible_shares

logger = logging.getLogger(__name__)

MAX_SHARE_BYTES = 8 * 1024 * 1024
MAX_EDGE = 4096
PNG_MAGIC = b'\x89PNG\r\n\x1a\n'


def _user(request):
    return getattr(request, 'edubac_user', None) or request.user


def share_payload(share):
    return {
        'type': 'share',
        'id': share.pk,
        'title': share.title,
        'classroom_id': share.classroom_id,
        'classroom_name': share.classroom.name,
        'created_at': share.created_at.isoformat(),
        'when': share.when_label(),
        'image_url': reverse('whiteboard:share_image', args=[share.pk]),
        'view_url': reverse('whiteboard:share_view', args=[share.pk]),
    }


def _read_png(upload):
    if upload is None:
        raise ValueError('Image manquante.')
    raw = upload.read(MAX_SHARE_BYTES + 1)
    if not raw or len(raw) > MAX_SHARE_BYTES:
        raise ValueError('Image trop volumineuse (8 Mo maximum).')
    if not raw.startswith(PNG_MAGIC):
        raise ValueError('Le fichier doit être un PNG.')
    try:
        with Image.open(io.BytesIO(raw)) as image:
            image.verify()
        with Image.open(io.BytesIO(raw)) as image:
            if image.format != 'PNG':
                raise ValueError('Le fichier doit être un PNG.')
            if image.width > MAX_EDGE or image.height > MAX_EDGE or image.width < 1 or image.height < 1:
                raise ValueError('Dimensions d’image non acceptées.')
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        if str(exc) in {
            'Le fichier doit être un PNG.',
            'Dimensions d’image non acceptées.',
        }:
            raise
        raise ValueError('Image PNG illisible.') from exc
    return raw


def _notify(share):
    from notifications.services import notify_user
    link = reverse('whiteboard:share_view', args=[share.pk])
    for member in share.classroom.members.select_related('user'):
        notify_user(
            user=member.user,
            title='Whiteboard partagé',
            message=f'« {share.title} » a été partagé avec la classe {share.classroom.name}.',
            type='classroom',
            actor=share.teacher,
            link=link,
            send_email=False,
        )


def _broadcast(share):
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer
        layer = get_channel_layer()
        if not layer:
            return
        async_to_sync(layer.group_send)(
            f'whiteboard_share_{share.classroom_id}',
            {'type': 'share.event', 'payload': share_payload(share)},
        )
    except Exception:
        logger.warning('whiteboard share broadcast failed', exc_info=True)


@login_required_simple
@require_POST
def share_create(request):
    user = _user(request)
    if getattr(user, 'role', '') != 'teacher':
        return JsonResponse({'error': 'Accès réservé aux enseignants.'}, status=403)
    classroom_id = (request.POST.get('classroom_id') or '').strip()
    if not classroom_id.isdigit():
        return JsonResponse({'error': 'Choisissez une classe.'}, status=400)
    classroom = Classroom.objects.filter(pk=int(classroom_id), teacher=user, is_active=True).first()
    if classroom is None:
        return JsonResponse(
            {'error': 'Vous ne pouvez partager qu’avec une de vos classes.'},
            status=403,
        )
    title = (request.POST.get('title') or '').strip()[:200] or 'Whiteboard'
    try:
        raw = _read_png(request.FILES.get('image'))
    except ValueError as exc:
        return JsonResponse({'error': str(exc)}, status=400)

    share = WhiteboardShare(teacher=user, classroom=classroom, title=title)
    share.image.save(f'{uuid.uuid4().hex}.png', ContentFile(raw), save=True)
    try:
        _notify(share)
    except Exception:
        logger.warning('whiteboard share notification failed', exc_info=True)
    _broadcast(share)
    return JsonResponse({'ok': True, 'share': share_payload(share)})


def _deny():
    return HttpResponseForbidden('Accès refusé.')


@login_required_simple
@require_GET
def share_api(request):
    user = _user(request)
    classroom_id = (request.GET.get('classroom') or '').strip()
    qs = visible_shares(user).select_related('classroom')
    if classroom_id:
        if not classroom_id.isdigit():
            return JsonResponse({'error': 'Accès refusé'}, status=403)
        classroom = Classroom.objects.filter(pk=int(classroom_id)).first()
        if classroom is None or not user_can_access_classroom(user, classroom):
            return JsonResponse({'error': 'Accès refusé'}, status=403)
        qs = qs.filter(classroom=classroom)
    after = (request.GET.get('after') or '').strip()
    if after.isdigit():
        qs = qs.filter(pk__gt=int(after))
    shares = list(qs[:20])
    return JsonResponse({
        'shares': [share_payload(share) for share in shares],
    })


@login_required_simple
@require_GET
def share_view(request, pk):
    share = get_object_or_404(
        WhiteboardShare.objects.select_related('classroom', 'teacher'),
        pk=pk,
    )
    user = _user(request)
    if not user_can_view_share(user, share):
        return _deny()
    history = list(
        visible_shares(user).filter(classroom_id=share.classroom_id).select_related('classroom')[:30]
    )
    return render(request, 'whiteboard/share_view.html', {
        'share': share,
        'shares': history,
        'page_title': share.title,
        'is_teacher': getattr(user, 'role', '') == 'teacher',
    })


@login_required_simple
@require_GET
def share_image(request, pk):
    share = get_object_or_404(WhiteboardShare.objects.select_related('classroom'), pk=pk)
    user = _user(request)
    if not user_can_view_share(user, share):
        return _deny()
    try:
        handle = share.image.open('rb')
    except FileNotFoundError:
        return JsonResponse({'error': 'Image introuvable.'}, status=404)
    response = FileResponse(handle, content_type='image/png')
    response['Content-Disposition'] = 'inline; filename="whiteboard.png"'
    response['Cache-Control'] = 'private, no-store'
    return response
