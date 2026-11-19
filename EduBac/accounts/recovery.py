"""Code de récupération : mot de passe oublié sans e-mail ni professeur.

- Le code est montré une seule fois (après la connexion, ou depuis le profil) et
  seul son haché est conservé ; un nouveau code annule l'ancien.
- Sur la page « Mot de passe oublié », l'élève saisit son identifiant, son code
  et un nouveau mot de passe. Le code est alors consommé, les autres sessions
  sont déconnectées et un nouveau code lui est proposé.
- Les essais sont limités par compte et par adresse ; le message d'erreur est le
  même que le compte existe ou non.
"""
import secrets

from django.contrib import messages
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from .decorators import login_required_simple
from .forms import RecoveryCodeForm
from .models import User

ALPHABET = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'   # sans 0/O, 1/I/L
CODE_LENGTH = 12
MAX_FAILURES = 5
WINDOW_SECONDS = 15 * 60
_DUMMY_HASH = make_password('code-de-recuperation-factice')


def normalize(code):
    return ''.join(ch for ch in (code or '').upper() if ch.isalnum())


def issue_code(user):
    """Crée un nouveau code (l'ancien ne marche plus) et le renvoie en clair, une seule fois."""
    raw = ''.join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
    user.recovery_code_hash = make_password(raw)
    user.recovery_code_created_at = timezone.now()
    user.save(update_fields=('recovery_code_hash', 'recovery_code_created_at'))
    return '-'.join(raw[i:i + 4] for i in range(0, CODE_LENGTH, 4))


def needs_code(user):
    """Proposer un code après la connexion : élèves sans code."""
    return user.is_student() and not user.recovery_code_hash


def _safe_next(request, value):
    if value and url_has_allowed_host_and_scheme(
        value, allowed_hosts={request.get_host()}, require_https=request.is_secure(),
    ):
        return value
    return reverse('accounts:dashboard')


def _no_store(response):
    response['Cache-Control'] = 'no-store, no-cache, max-age=0, must-revalidate'
    response['Pragma'] = 'no-cache'
    response['Referrer-Policy'] = 'same-origin'
    return response


@login_required_simple
@require_http_methods(['GET', 'POST'])
def recovery_code(request):
    user = request.edubac_user
    next_url = _safe_next(request, request.POST.get('suite') or request.GET.get('suite'))
    code = issue_code(user) if request.method == 'POST' else None
    return _no_store(render(request, 'accounts/recovery_code.html', {
        'page_title': 'Code de récupération',
        'code': code,
        'has_code': bool(user.recovery_code_hash),
        'created_at': user.recovery_code_created_at,
        'next_url': next_url,
        'first_time': request.GET.get('premiere') == '1' or request.POST.get('premiere') == '1',
    }))


def _client_address(request):
    return request.META.get('HTTP_X_REAL_IP') or request.META.get('REMOTE_ADDR', '')


def _keys(request, identifier):
    return (f'recovery-fail:id:{identifier.lower()}', f'recovery-fail:ip:{_client_address(request)}')


def _blocked(keys):
    return any(cache.get(key, 0) >= MAX_FAILURES for key in keys)


def _failed(keys):
    for key in keys:
        if not cache.add(key, 1, timeout=WINDOW_SECONDS):
            try:
                cache.incr(key)
            except ValueError:
                cache.add(key, 1, timeout=WINDOW_SECONDS)


@never_cache
@require_http_methods(['GET', 'POST'])
def recover_with_code(request):
    if getattr(request, 'edubac_user', None):
        return redirect('accounts:dashboard')
    form = RecoveryCodeForm(request.POST or None)
    error = None
    if request.method == 'POST' and form.is_valid():
        identifier = form.cleaned_data['username'].strip()
        keys = _keys(request, identifier)
        if _blocked(keys):
            error = ('Trop d’essais. Attendez 15 minutes, ou demandez un nouveau mot de passe '
                     'à votre professeur.')
        else:
            user = (
                User.objects.filter(Q(username__iexact=identifier) | Q(email__iexact=identifier))
                .exclude(recovery_code_hash='').first()
            )
            code_ok = check_password(normalize(form.cleaned_data['code']),
                                     user.recovery_code_hash if user else _DUMMY_HASH)
            usable = bool(user and code_ok and user.is_active and user.approval_status == 'approved')
            if not usable:
                _failed(keys)
                error = 'Identifiant ou code de récupération incorrect.'
            else:
                password = form.cleaned_data['new_password1']
                try:
                    validate_password(password, user=user)
                except ValidationError as exc:
                    form.add_error('new_password1', exc)
                else:
                    with transaction.atomic():
                        user = User.objects.select_for_update().get(pk=user.pk)
                        user.set_password(password)
                        user.must_change_password = False
                        user.recovery_code_hash = ''          # utilisable une seule fois
                        user.password_session_version += 1    # déconnecte les autres appareils
                        user.save(update_fields=('password', 'must_change_password',
                                                 'recovery_code_hash', 'password_session_version'))
                    for key in keys:
                        cache.delete(key)
                    from .views import _login_session
                    _login_session(request, user)
                    messages.success(request, 'Mot de passe modifié. Notez maintenant votre nouveau code de récupération.')
                    return redirect(reverse('accounts:recovery_code') + '?premiere=1')
    return _no_store(render(request, 'accounts/recover_with_code.html', {
        'page_title': 'Nouveau mot de passe avec mon code',
        'form': form,
        'error': error,
    }))
