from django.contrib import messages
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from accounts.decorators import login_required_simple

from . import catalog
from .models import Notification, NotificationPreference


def _recipient(request):
    return getattr(request, 'edubac_user', None) or request.user


def _limit(request, default=20, maximum=50):
    try:
        value = int(request.GET.get('limit', default))
    except (TypeError, ValueError):
        return default
    return max(1, min(value, maximum))


@login_required_simple
@require_GET
def api_list(request):
    """
    Notifications non lues de l'utilisateur connecté (menu de la cloche).
    GET /notifications/api/?limit=20
    """
    unread_qs = Notification.objects.filter(recipient=_recipient(request), is_read=False)
    data = {
        'unread_count': unread_qs.count(),
        'notifications': [
            {
                'id': n.id,
                'type': n.type,
                'title': n.title,
                'message': n.message,
                'link': n.safe_link,
                'is_read': n.is_read,
                'count': n.count,
                'time_ago': n.time_ago,
                'created_at': n.updated_at.isoformat(),
            }
            for n in unread_qs[:_limit(request)]
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


# ─── Pages ───────────────────────────────────────────────────────────────────

@login_required_simple
@require_GET
def history(request):
    """Toutes les notifications, lues ou non, avec filtres."""
    user = _recipient(request)
    qs = Notification.objects.filter(recipient=user).select_related('actor')
    available = [(code, catalog.TYPES[code]['label']) for code in catalog.types_for(user)]
    selected_type = request.GET.get('type', '')
    if selected_type in dict(available):
        qs = qs.filter(type=selected_type)
    else:
        selected_type = ''
    only_unread = request.GET.get('etat') == 'non-lues'
    if only_unread:
        qs = qs.filter(is_read=False)
    page = Paginator(qs, 30).get_page(request.GET.get('page'))
    return render(request, 'notifications/history.html', {
        'page_obj': page,
        'types': available,
        'selected_type': selected_type,
        'only_unread': only_unread,
        'unread_count': Notification.objects.filter(recipient=user, is_read=False).count(),
        'page_title': 'Mes notifications',
    })


@login_required_simple
@require_POST
def open_notification(request, pk):
    """Marque comme lue puis ouvre le lien (interne uniquement)."""
    notification = get_object_or_404(Notification, pk=pk, recipient=_recipient(request))
    notification.mark_as_read()
    return redirect(notification.safe_link or 'notifications:history')


@login_required_simple
@require_POST
def mark_all_read(request):
    Notification.objects.filter(recipient=_recipient(request), is_read=False).update(is_read=True)
    messages.success(request, 'Toutes les notifications sont marquées comme lues.')
    return redirect('notifications:history')


@login_required_simple
@require_http_methods(['GET', 'POST'])
def preferences(request):
    """Choix des canaux, type par type."""
    user = _recipient(request)
    current = NotificationPreference.all_for_user(user)
    has_email = bool(user.email and '@' in user.email)
    if request.method == 'POST':
        values = {}
        for code in current:
            email = request.POST.get(f'email_{code}', current[code]['email'])
            if email not in dict(catalog.EMAIL_CHOICES) or not has_email:
                email = current[code]['email']
            values[code] = {
                'in_app': request.POST.get(f'in_app_{code}') == 'on',
                'email': email,
            }
        NotificationPreference.objects.update_or_create(user=user, defaults={'values': values})
        messages.success(request, 'Préférences de notification enregistrées.')
        return redirect('notifications:preferences')
    rows = [
        {
            'code': code,
            'label': catalog.TYPES[code]['label'],
            'icon': catalog.TYPES[code]['icon'],
            'in_app': pref['in_app'],
            'email': pref['email'],
        }
        for code, pref in current.items()
    ]
    return render(request, 'notifications/preferences.html', {
        'rows': rows,
        'email_choices': catalog.EMAIL_CHOICES,
        'has_email': has_email,
        'page_title': 'Préférences de notification',
    })
