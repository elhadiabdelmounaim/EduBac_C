"""Mot de passe oublié sans e-mail : l'élève envoie son nom depuis la page de
connexion, le professeur-administrateur (superutilisateur) est prévenu, vérifie
l'identité de l'élève puis lui crée un mot de passe temporaire depuis
l'administration (accounts.views.reset_student_password).

La réponse au visiteur est toujours la même, que le nom corresponde à un compte
ou non : la page ne permet pas de deviner qui est inscrit.
"""
from datetime import timedelta

from django.contrib import messages
from django.core.cache import cache
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from .decorators import superuser_required
from .models import PasswordHelpRequest, User

MAX_PER_HOUR = 5          # demandes par appareil / adresse et par heure
MAX_PENDING = 300         # au-delà, on n'enregistre plus (protection anti-abus)
DUPLICATE_WINDOW = timedelta(days=7)


def _students():
    return User.objects.filter(role='student', is_staff=False, is_superuser=False)


def match_student(name):
    """L'élève correspondant sans ambiguïté au nom saisi, sinon None."""
    name = ' '.join(name.split())
    if not name:
        return None
    query = Q(username__iexact=name) | Q(email__iexact=name)
    terms = name.split(' ')
    if len(terms) >= 2:
        full = Q()
        for term in terms:
            full &= Q(first_name__iexact=term) | Q(last_name__iexact=term)
        query |= full
    found = list(_students().filter(query)[:2])
    return found[0] if len(found) == 1 else None


def _client_key(request):
    # PythonAnywhere place l'adresse du visiteur dans X-Real-IP.
    address = request.META.get('HTTP_X_REAL_IP') or request.META.get('REMOTE_ADDR', '')
    return f'password-help:{address}'


def _over_limit(request):
    key = _client_key(request)
    if cache.add(key, 1, timeout=3600):
        return False
    try:
        count = cache.incr(key)
    except ValueError:
        cache.add(key, 1, timeout=3600)
        return False
    return count > MAX_PER_HOUR


def _notify_administrators(help_request):
    from notifications.models import Notification

    who = help_request.name
    if help_request.classroom_hint:
        who += f' ({help_request.classroom_hint})'
    link = reverse('accounts:admin_dashboard') + '#password-requests'
    for admin in User.objects.filter(is_superuser=True, is_active=True):
        Notification.notify(
            admin,
            'Mot de passe oublié',
            f'{who} demande un nouveau mot de passe.',
            type='account',
            link=link,
            send_email=False,
            group_key='password-help',
        )


@never_cache
@require_http_methods(['GET', 'POST'])
def forgot_password(request):
    if getattr(request, 'edubac_user', None):
        return redirect('accounts:dashboard')
    if request.GET.get('envoye') == '1':
        return render(request, 'accounts/forgot_password.html', {
            'page_title': 'Mot de passe oublié', 'sent': True,
        })

    values = {'name': '', 'classroom': ''}
    error = None
    if request.method == 'POST':
        values = {
            'name': ' '.join((request.POST.get('name') or '').split())[:150],
            'classroom': ' '.join((request.POST.get('classroom') or '').split())[:100],
        }
        if request.POST.get('website'):
            # Champ invisible rempli : robot. On répond comme si tout allait bien.
            return redirect(reverse('accounts:forgot_password') + '?envoye=1')
        if len(values['name']) < 3:
            error = 'Indiquez votre nom et prénom (ou votre identifiant).'
        elif _over_limit(request):
            error = 'Trop de demandes envoyées. Réessayez dans une heure ou parlez directement à votre professeur.'
        else:
            pending = PasswordHelpRequest.objects.filter(status=PasswordHelpRequest.STATUS_PENDING)
            duplicate = pending.filter(
                name__iexact=values['name'],
                created_at__gte=timezone.now() - DUPLICATE_WINDOW,
            ).exists()
            if not duplicate and pending.count() < MAX_PENDING:
                help_request = PasswordHelpRequest.objects.create(
                    name=values['name'],
                    classroom_hint=values['classroom'],
                    student=match_student(values['name']),
                )
                _notify_administrators(help_request)
            return redirect(reverse('accounts:forgot_password') + '?envoye=1')

    return render(request, 'accounts/forgot_password.html', {
        'page_title': 'Mot de passe oublié',
        'values': values,
        'error': error,
    })


def pending_requests():
    return list(
        PasswordHelpRequest.objects
        .filter(status=PasswordHelpRequest.STATUS_PENDING)
        .select_related('student')
        .order_by('created_at')[:100]
    )


def close_requests(student, administrator, request_id=None):
    """Après une réinitialisation : les demandes de cet élève sont traitées."""
    now = timezone.now()
    pending = PasswordHelpRequest.objects.filter(status=PasswordHelpRequest.STATUS_PENDING)
    if request_id:
        pending.filter(pk=request_id, student__isnull=True).update(student=student)
    pending.filter(Q(student=student) | Q(pk=request_id or 0)).update(
        status=PasswordHelpRequest.STATUS_DONE, handled_at=now, handled_by=administrator,
    )


@superuser_required
@require_POST
def dismiss_password_request(request, request_id):
    help_request = get_object_or_404(
        PasswordHelpRequest, pk=request_id, status=PasswordHelpRequest.STATUS_PENDING,
    )
    help_request.status = PasswordHelpRequest.STATUS_DISMISSED
    help_request.handled_at = timezone.now()
    help_request.handled_by = request.edubac_user
    help_request.save(update_fields=('status', 'handled_at', 'handled_by'))
    messages.info(request, f'Demande de « {help_request.name} » ignorée.')
    return redirect(reverse('accounts:admin_dashboard') + '#password-requests')
