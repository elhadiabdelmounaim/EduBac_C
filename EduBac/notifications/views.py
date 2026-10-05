import json
from accounts.decorators import login_required_simple
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import ensure_csrf_cookie
from .models import Notification

def _recipient(request):
    return getattr(request, 'edubac_user', None) or request.user


@login_required_simple
@require_GET
def api_list(request):
    """
    Liste les notifications de l'utilisateur connecté.
    GET /notifications/api/?limit=20
    """
    limit = min(int(request.GET.get('limit', 20)), 50)
    qs = Notification.objects.filter(recipient=_recipient(request), is_read=False)[:limit]
    unread = Notification.objects.filter(recipient=_recipient(request), is_read=False).count()

    data = {
        'unread_count': unread,
        'notifications': [
            {
                'id': n.id,
                'type': n.type,
                'title': n.title,
                'message': n.message,
                'link': n.link,
                'is_read': n.is_read,
                'time_ago': n.time_ago,
                'created_at': n.created_at.isoformat(),
            }
            for n in qs
        ],
    }
    return JsonResponse(data)


@login_required_simple
@require_GET
def api_unread_count(request):
    """Compteur seul — léger pour le polling."""
    count = Notification.objects.filter(recipient=_recipient(request), is_read=False).count()
    return JsonResponse({'unread_count': count})


@login_required_simple
@require_POST
def api_mark_read(request, pk):
    """Marque une notification comme lue."""
    try:
        notif = Notification.objects.get(pk=pk, recipient=_recipient(request))
    except Notification.DoesNotExist:
        return JsonResponse({'error': 'Notification introuvable.'}, status=404)
    notif.mark_as_read()
    unread = Notification.objects.filter(recipient=_recipient(request), is_read=False).count()
    return JsonResponse({'ok': True, 'unread_count': unread})


@login_required_simple
@require_POST
def api_mark_all_read(request):
    """Marque toutes les notifications comme lues."""
    updated = Notification.objects.filter(
        recipient=_recipient(request), is_read=False
    ).update(is_read=True)
    return JsonResponse({'ok': True, 'marked': updated, 'unread_count': 0})
