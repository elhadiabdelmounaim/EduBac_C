import logging
import secrets
import uuid

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.http import HttpResponseForbidden
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from django.db.models import Count, Avg, Q, Prefetch
from django.core import signing
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import (
    User,
    StudentProfile,
    TeacherProfile,
    StudentPasswordResetEvent,
)
from .decorators import (
    admin_required,
    login_required_simple,
    student_required,
    superuser_required,
    teacher_required,
)
from .forms import ForcedPasswordChangeForm
from .email_verification import (
    get_user_from_verification_token,
    send_verification_email,
    verification_expiry_label,
)
from .services import compute_student_progress


logger = logging.getLogger(__name__)


def _split_name(full_name: str):
    full_name = (full_name or '').strip()
    if not full_name:
        return '', ''
    parts = full_name.split(None, 1)
    if len(parts) == 1:
        return parts[0], ''
    return parts[0], parts[1]


def _make_username(first_name, last_name, email):
    import re
    import unicodedata

    def slug(s):
        s = unicodedata.normalize('NFKD', s or '').encode('ascii', 'ignore').decode('ascii')
        s = re.sub(r'[^a-zA-Z0-9]+', '', s).lower()
        return s or 'user'

    base = f"{slug(first_name)}.{slug(last_name)}".strip('.')
    if not base or base == '.':
        base = slug(email.split('@')[0]) or 'user'
    username = base
    n = 1
    while User.objects.filter(username=username).exists():
        n += 1
        username = f"{base}{n}"
    return username


def _authenticate(request):
    """Email + password. Retourne (user, error) sans filtrer le rôle."""
    identifiant = (request.POST.get('email') or request.POST.get('username') or '').strip()
    password = request.POST.get('password') or ''
    if not identifiant or not password:
        return None, 'Veuillez remplir tous les champs.'
    user = User.objects.filter(email__iexact=identifiant).first()
    if user is None:
        user = User.objects.filter(username=identifiant).first()
    if user is None or not user.check_password(password):
        return None, 'E-mail ou mot de passe incorrect.'
    if user.approval_status == 'pending':
        return None, 'Votre demande d’inscription attend la validation de l’administrateur.'
    if not user.is_active:
        return None, 'Ce compte est désactivé.'
    return user, None


def _valid_email(value):
    try:
        validate_email(value)
    except ValidationError:
        return False
    return True


def _find_user_by_email(email):
    return User.objects.filter(email__iexact=email).first()


def _duplicate_registration_response(request, user, role):
    if not user.email_verified:
        request.session['email_verification_pending'] = user.email
        messages.info(
            request,
            'Cette adresse correspond déjà à un compte non vérifié. '
            'Aucun nouveau compte n’a été créé. Tu peux demander un nouveau '
            'lien de vérification ci-dessous.',
        )
        return redirect('accounts:email_verification_pending')

    context = {
        'page_title': (
            'Inscription élève' if role == 'student'
            else 'Inscription enseignant'
        ),
        'error': (
            'Cette adresse e-mail est déjà utilisée. Connecte-toi avec ce '
            'compte ou utilise une autre adresse e-mail.'
        ),
    }
    if role == 'student':
        context['niveaux'] = StudentProfile.NIVEAU_CHOICES
        template = 'accounts/register_student.html'
    else:
        template = 'accounts/register_teacher.html'
    return render(request, template, context)


def _create_registration_account(
    email,
    password,
    first_name,
    last_name,
    role,
    niveau='tronc_commun',
):
    user = User(
        username=_make_username(first_name, last_name, email),
        email=email,
        email_verified=False,
        role=role,
        first_name=first_name or email.split('@')[0],
        last_name=last_name,
    )
    user.set_password(password)

    # Keep the user and its role-specific profile as one database operation.
    with transaction.atomic():
        user.save()
        if role == 'student':
            StudentProfile.objects.create(user=user, niveau=niveau)
        else:
            TeacherProfile.objects.create(
                user=user,
                subject='Mathématiques',
            )
    return user


def _register_account(
    request,
    *,
    email,
    password,
    first_name,
    last_name,
    role,
    niveau='tronc_commun',
):
    existing = _find_user_by_email(email)
    if existing is not None:
        return _duplicate_registration_response(request, existing, role)

    try:
        user = _create_registration_account(
            email,
            password,
            first_name,
            last_name,
            role,
            niveau,
        )
    except IntegrityError:
        # Another request may have inserted this address after the lookup.
        # Catch outside atomic(), then re-read the committed winner.
        existing = _find_user_by_email(email)
        if existing is None:
            raise
        return _duplicate_registration_response(request, existing, role)

    return _send_verification_after_signup(request, user)


def _send_verification_after_signup(request, user):
    request.session['email_verification_pending'] = user.email
    status = send_verification_email(request, user)
    if status not in {'sent', 'rate_limited', 'failed'}:
        status = 'failed'
    pending_url = reverse('accounts:email_verification_pending')
    return redirect(f'{pending_url}?status={status}')


def _login_session(request, user):
    request.session['user_id'] = user.id
    request.session['role'] = user.role
    request.session['password_session_version'] = user.password_session_version
    request.session.cycle_key()


def login_view(request, *, teacher_entry=False):
    """
    Login unique : e-mail + mot de passe.
    Le backend détermine le rôle et redirige.
    """
    if getattr(request, 'edubac_user', None) and request.method != 'POST':
        if teacher_entry and request.edubac_user.is_teacher():
            return redirect('accounts:teacher_portal')
        return redirect('accounts:dashboard')
    error = None
    if request.method == 'POST':
        user, error = _authenticate(request)
        if user:
            if teacher_entry and not user.is_teacher():
                error = 'Ce formulaire est réservé aux professeurs et aux administrateurs.'
            else:
                if user.is_staff or user.is_superuser:
                    _login_session(request, user)
                    return redirect('accounts:teacher_portal')
                if user.must_change_password:
                    _login_session(request, user)
                    return redirect('accounts:change_password')
                if not user.email_verified and not user.password_reset_at:
                    request.session['email_verification_pending'] = user.email
                    messages.warning(
                        request,
                        'Cette adresse e-mail n’est pas encore vérifiée.',
                    )
                    return redirect('accounts:email_verification_pending')
                _login_session(request, user)
                messages.success(
                    request,
                    f'Bienvenue, {user.get_full_name() or user.username} !'
                )
                return redirect(
                    'accounts:teacher_portal'
                    if teacher_entry
                    else 'accounts:dashboard'
                )
    return render(request, (
        'accounts/login_teacher.html'
        if teacher_entry
        else 'accounts/login.html'
    ), {
        'page_title': 'Connexion enseignant' if teacher_entry else 'Connexion',
        'error': error,
    })


# Alias : anciennes URLs élève/prof → login unique
def login_student(request):
    return login_view(request)


def login_teacher(request):
    return login_view(request, teacher_entry=True)


def logout_view(request):
    request.session.flush()
    messages.info(request, 'Vous êtes déconnecté.')
    return redirect('education:home')


def admin_teacher_dashboard(request):
    """Transfer an authenticated Django admin session into the teacher area."""
    user = request.user
    if not getattr(user, 'is_authenticated', False):
        return redirect('admin:login')
    if not (user.is_staff or user.is_superuser):
        return HttpResponseForbidden('Accès réservé au compte administrateur enseignant.')

    request.session['user_id'] = user.pk
    request.session['role'] = user.role
    request.session.cycle_key()
    return redirect('accounts:teacher_portal')


def register(request):
    """Inscription élève (par défaut publique)."""
    return register_student(request)


def register_choice(request):
    """Plus de choix de rôle : redirige vers inscription élève."""
    return redirect('accounts:register_student')


def register_student(request):
    """
    Inscription élève : nom complet, nom d’utilisateur, mot de passe et code classe.
    Le compte reste inaccessible jusqu’à son approbation par l’administrateur.
    """
    if getattr(request, 'edubac_user', None):
        return redirect('accounts:dashboard')
    error = None
    if request.method == 'POST':
        full_name = (request.POST.get('name') or request.POST.get('full_name') or '').strip()
        username = (request.POST.get('username') or '').strip()
        password = request.POST.get('password') or ''
        password2 = request.POST.get('password2') or ''
        class_code = (request.POST.get('class_code') or '').strip().upper()

        if not full_name:
            error = 'Le nom est obligatoire.'
        elif not username:
            error = 'Le nom d’utilisateur est obligatoire.'
        elif len(username) > 150:
            error = 'Le nom d’utilisateur ne peut pas dépasser 150 caractères.'
        elif User.objects.filter(username__iexact=username).exists():
            error = 'Ce nom d’utilisateur est déjà utilisé.'
        elif not password:
            error = 'Le mot de passe est obligatoire.'
        elif password != password2:
            error = 'Les mots de passe ne correspondent pas.'
        elif len(password) < 6:
            error = 'Le mot de passe doit contenir au moins 6 caractères.'
        elif not class_code:
            error = 'Le code de classe est obligatoire.'
        else:
            try:
                User._meta.get_field('username').clean(username, None)
            except ValidationError:
                error = 'Le nom d’utilisateur contient des caractères non autorisés.'

            if not error:
                from classrooms.models import Classroom, ClassroomMember

                classroom = Classroom.objects.filter(
                    code__iexact=class_code,
                ).first()
                if classroom is None:
                    error = (
                        'Classe introuvable. Veuillez vérifier le code de classe '
                        'et réessayer.'
                    )
                elif not classroom.is_active:
                    error = (
                        "Ce code de classe n'est plus actif. Veuillez contacter "
                        "l'administrateur."
                    )
                else:
                    first_name, last_name = _split_name(full_name)
                    try:
                        with transaction.atomic():
                            user = User(
                                username=username,
                                email=None,
                                email_verified=True,
                                approval_status='pending',
                                is_active=False,
                                role='student',
                                first_name=first_name,
                                last_name=last_name,
                            )
                            user.set_password(password)
                            user.save()
                            StudentProfile.objects.create(
                                user=user,
                                niveau=classroom.niveau,
                            )
                            ClassroomMember.objects.create(
                                classroom=classroom,
                                user=user,
                            )
                    except IntegrityError:
                        error = 'Ce nom d’utilisateur est déjà utilisé.'
                    else:
                        messages.success(
                            request,
                            'Votre demande a été envoyée. Connectez-vous après '
                            'son approbation par l’administrateur.',
                        )
                        return redirect('accounts:login')

    return render(request, 'accounts/register_student.html', {
        'page_title': 'Inscription élève',
        'error': error,
    })


def register_teacher(request):
    """Retired public teacher signup; all public registrations are for students."""
    return redirect('accounts:register_student')


@require_GET
def email_verification_pending(request):
    send_status = request.GET.get('status', '')
    if send_status not in {'sent', 'rate_limited', 'failed'}:
        send_status = ''
    return render(request, 'accounts/email_verification_pending.html', {
        'page_title': 'Vérification de l’e-mail',
        'email': request.session.get('email_verification_pending', ''),
        'send_status': send_status,
        'expiry_label': verification_expiry_label(),
        'link_expired': request.GET.get('expired') == '1',
        'invalid_link': request.GET.get('invalid') == '1',
    })


@require_POST
def resend_verification(request):
    attempt_id = uuid.uuid4().hex[:12]
    logger.info(
        'verification_resend attempt_id=%s stage=request outcome=received',
        attempt_id,
    )
    email = (request.POST.get('email') or '').strip().lower()
    if not _valid_email(email):
        logger.warning(
            'verification_resend attempt_id=%s stage=input outcome=invalid',
            attempt_id,
        )
        messages.error(request, 'Saisis une adresse e-mail valide.')
        return redirect('accounts:email_verification_pending')

    request.session['email_verification_pending'] = email
    user = User.objects.filter(email__iexact=email).first()
    if user is None:
        logger.info(
            'verification_resend attempt_id=%s stage=user_lookup outcome=not_found',
            attempt_id,
        )
    elif user.email_verified:
        logger.info(
            'verification_resend attempt_id=%s stage=user_lookup outcome=already_verified',
            attempt_id,
        )
    else:
        logger.info(
            'verification_resend attempt_id=%s stage=user_lookup outcome=eligible',
            attempt_id,
        )
        send_result = send_verification_email(
            request,
            user,
            attempt_id=attempt_id,
        )
        logger.info(
            'verification_resend attempt_id=%s stage=send_service outcome=%s',
            attempt_id,
            send_result,
        )

    # Keep the same response for unknown, verified, and unverified addresses.
    # This also intentionally avoids exposing transport results to the browser.
    messages.success(
        request,
        'Si cette adresse correspond à un compte non vérifié, '
        'un nouveau lien a été envoyé si la demande est autorisée. '
        'Vérifie aussi les courriers indésirables.',
    )
    logger.info(
        'verification_resend attempt_id=%s stage=response outcome=redirect',
        attempt_id,
    )
    return redirect('accounts:email_verification_pending')


@require_GET
def confirm_email(request, token):
    try:
        user = get_user_from_verification_token(token)
    except signing.SignatureExpired:
        return render(request, 'accounts/email_verification_pending.html', {
            'page_title': 'Lien expiré',
            'email': request.session.get('email_verification_pending', ''),
            'expiry_label': verification_expiry_label(),
            'link_expired': True,
        })
    except (signing.BadSignature, User.DoesNotExist, KeyError, TypeError, ValueError):
        return render(
            request,
            'accounts/email_verification_pending.html',
            {
                'page_title': 'Lien invalide',
                'email': request.session.get('email_verification_pending', ''),
                'expiry_label': verification_expiry_label(),
                'invalid_link': True,
            },
            status=400,
        )

    already_verified = user.email_verified
    if not already_verified:
        user.email_verified = True
        user.save(update_fields=['email_verified'])
    if request.session.get('email_verification_pending', '').casefold() == user.email.casefold():
        request.session.pop('email_verification_pending', None)
    return render(request, 'accounts/email_verified.html', {
        'page_title': 'Adresse e-mail vérifiée',
        'already_verified': already_verified,
    })


@login_required_simple
def profile(request):
    user = request.edubac_user
    context = {'page_title': 'Profil', 'user': user}
    if user.is_student() and hasattr(user, 'student_profile'):
        context['profile'] = user.student_profile
        context['stats'] = compute_student_progress(user)
    elif user.is_teacher() and hasattr(user, 'teacher_profile'):
        context['profile'] = user.teacher_profile
    return render(request, 'accounts/profile.html', context)


@login_required_simple
def dashboard(request):
    if request.edubac_user.is_teacher():
        return teacher_dashboard(request)
    return student_dashboard(request)


@admin_required
def admin_dashboard(request):
    from classrooms.models import ClassroomMember

    current_user = request.edubac_user
    pending_users = User.objects.filter(
        role='student',
        approval_status='pending',
    ).order_by('date_joined')
    registrations = [
        {
            'user': user,
            'membership': ClassroomMember.objects.filter(
                user=user,
            ).select_related('classroom').first(),
        }
        for user in pending_users
    ]
    student_search = (request.GET.get('student_q') or '').strip()
    student_results = []
    if current_user.is_superuser and student_search:
        memberships = ClassroomMember.objects.select_related('classroom')
        student_results = list(
            User.objects.filter(
                role='student',
                is_staff=False,
                is_superuser=False,
            )
            .filter(
                Q(username__icontains=student_search)
                | Q(first_name__icontains=student_search)
                | Q(last_name__icontains=student_search)
            )
            .select_related('student_profile')
            .prefetch_related(
                Prefetch('classroom_memberships', queryset=memberships)
            )
            .order_by('last_name', 'first_name', 'username')[:50]
        )
        for student in student_results:
            student_memberships = list(student.classroom_memberships.all())
            student.admin_classroom = (
                student_memberships[0].classroom.name
                if student_memberships else None
            )
            try:
                profile = student.student_profile
            except StudentProfile.DoesNotExist:
                profile = None
            student.admin_level = (
                profile.get_niveau_display() if profile else 'Non renseigné'
            )
            if student.approval_status == 'pending':
                student.admin_status = 'En attente d’approbation'
            elif not student.is_active:
                student.admin_status = 'Désactivé'
            elif student.must_change_password:
                student.admin_status = 'Changement de mot de passe requis'
            else:
                student.admin_status = 'Actif'
            student.can_reset_password = (
                student.approval_status == 'approved' and student.is_active
            )

    return render(request, 'accounts/dashboard_admin.html', {
        'page_title': 'Administration EduBac',
        'registrations': registrations,
        'pending_count': len(registrations),
        'student_search': student_search,
        'student_results': student_results,
        'student_search_performed': bool(student_search and current_user.is_superuser),
        'student_results_limit_reached': len(student_results) == 50,
    })


def _student_reset_context(student, *, nonce='', error=None):
    from classrooms.models import ClassroomMember

    membership = (
        ClassroomMember.objects.filter(user=student)
        .select_related('classroom')
        .first()
    )
    try:
        profile = student.student_profile
    except StudentProfile.DoesNotExist:
        profile = None
    return {
        'page_title': 'Réinitialiser le mot de passe',
        'student': student,
        'classroom': membership.classroom if membership else None,
        'level': profile.get_niveau_display() if profile else 'Non renseigné',
        'nonce': nonce,
        'error': error,
        'account_status': (
            'En attente d’approbation'
            if student.approval_status == 'pending'
            else 'Désactivé'
            if not student.is_active
            else 'Changement de mot de passe requis'
            if student.must_change_password
            else 'Actif'
        ),
    }


def _no_store(response):
    response['Cache-Control'] = 'no-store, no-cache, max-age=0, must-revalidate'
    response['Pragma'] = 'no-cache'
    response['Referrer-Policy'] = 'no-referrer'
    return response


@superuser_required
@require_GET
def confirm_student_password_reset(request, user_id):
    student = get_object_or_404(
        User,
        pk=user_id,
        role='student',
        is_staff=False,
        is_superuser=False,
    )
    nonce = secrets.token_urlsafe(24)
    pending = request.session.get('student_password_reset_nonces', {})
    if not isinstance(pending, dict):
        pending = {}
    pending[str(student.pk)] = nonce
    request.session['student_password_reset_nonces'] = pending
    return _no_store(render(
        request,
        'accounts/confirm_student_password_reset.html',
        _student_reset_context(student, nonce=nonce),
    ))


@superuser_required
@require_POST
def reset_student_password(request, user_id):
    student = get_object_or_404(
        User,
        pk=user_id,
        role='student',
        is_staff=False,
        is_superuser=False,
    )
    pending = request.session.get('student_password_reset_nonces', {})
    expected_nonce = pending.get(str(student.pk)) if isinstance(pending, dict) else None
    supplied_nonce = request.POST.get('nonce', '')
    if (
        not expected_nonce
        or not supplied_nonce
        or not secrets.compare_digest(expected_nonce, supplied_nonce)
    ):
        messages.error(
            request,
            'Cette confirmation a expiré. Recherchez de nouveau l’élève.',
        )
        return redirect('accounts:admin_dashboard')

    if request.POST.get('identity_verified') != 'yes':
        return _no_store(render(
            request,
            'accounts/confirm_student_password_reset.html',
            _student_reset_context(
                student,
                nonce=expected_nonce,
                error='Confirmez d’abord que vous avez vérifié l’identité de l’élève.',
            ),
        ))

    pending.pop(str(student.pk), None)
    request.session['student_password_reset_nonces'] = pending
    with transaction.atomic():
        student = User.objects.select_for_update().filter(
            pk=student.pk,
            role='student',
            is_staff=False,
            is_superuser=False,
            approval_status='approved',
            is_active=True,
        ).first()
        if student is None:
            messages.error(
                request,
                'Seul un compte élève actif et approuvé peut être réinitialisé.',
            )
            return redirect('accounts:admin_dashboard')

        temporary_password = secrets.token_urlsafe(24)
        student.set_password(temporary_password)
        student.must_change_password = True
        student.password_reset_at = timezone.now()
        student.password_session_version += 1
        student.save(update_fields=(
            'password',
            'must_change_password',
            'password_reset_at',
            'password_session_version',
        ))
        administrator = request.edubac_user
        StudentPasswordResetEvent.objects.create(
            student=student,
            student_username=student.username,
            administrator=administrator,
            administrator_id_snapshot=administrator.pk,
            administrator_username=administrator.username,
        )

    response = render(
        request,
        'accounts/student_password_reset_result.html',
        {
            'page_title': 'Mot de passe temporaire',
            'student': student,
            'temporary_password': temporary_password,
        },
    )
    return _no_store(response)


@login_required_simple
@require_http_methods(['GET', 'POST'])
def change_password(request):
    user = request.edubac_user
    if not user.must_change_password:
        return redirect('accounts:dashboard')

    form = ForcedPasswordChangeForm(
        request.POST or None,
        user=user,
    )
    if request.method == 'POST' and form.is_valid():
        user.set_password(form.cleaned_data['new_password1'])
        user.must_change_password = False
        user.save(update_fields=('password', 'must_change_password'))
        request.session['password_session_version'] = user.password_session_version
        request.session.cycle_key()
        messages.success(request, 'Votre mot de passe a été modifié.')
        return redirect('accounts:dashboard')

    return _no_store(render(
        request,
        'accounts/change_password.html',
        {
            'page_title': 'Changer votre mot de passe',
            'form': form,
        },
    ))


@admin_required
@require_POST
def review_registration(request, user_id):
    action = request.POST.get('action')
    if action not in {'approve', 'reject'}:
        return redirect('accounts:admin_dashboard')

    with transaction.atomic():
        user = User.objects.select_for_update().filter(
            pk=user_id,
            role='student',
            approval_status='pending',
        ).first()
        if user is None:
            messages.warning(request, 'Cette demande a déjà été traitée.')
            return redirect('accounts:admin_dashboard')

        if action == 'approve':
            user.approval_status = 'approved'
            user.is_active = True
            user.save(update_fields=['approval_status', 'is_active'])
            messages.success(
                request,
                f'Le compte de {user.get_full_name()} a été approuvé.',
            )
        else:
            user.delete()
            messages.success(request, 'La demande et le compte élève ont été supprimés.')

    return redirect('accounts:admin_dashboard')


@student_required
def student_dashboard(request):
    from education.models import Course
    from quizzes.models import QuizAssignment, Attempt, Quiz
    from accounts.engagement import get_streak, weekly_goal_progress, ensure_badges, record_activity
    from accounts.models import UserBadge

    ensure_badges()
    user = request.edubac_user
    record_activity(user)
    profile = getattr(user, 'student_profile', None)
    stats = compute_student_progress(user)
    courses = Course.objects.filter(niveau=profile.niveau).order_by('order')[:6] if profile else Course.objects.none()
    assignments = QuizAssignment.objects.filter(student=user).select_related('quiz').order_by('-assigned_at')[:5]
    recent_attempts = Attempt.objects.filter(student=user, submitted_at__isnull=False).select_related('quiz').order_by('-submitted_at')[:5]
    streak = get_streak(user)
    weekly = weekly_goal_progress(user)
    recent_badges = UserBadge.objects.filter(user=user).select_related('badge')[:5]
    from accounts.models import WeeklyChallenge
    from django.utils import timezone
    active_challenge = WeeklyChallenge.objects.filter(
        active=True, start_date__lte=timezone.localdate(), end_date__gte=timezone.localdate()
    ).first()
    from classrooms.models import ClassroomMember
    from whiteboard.models import WhiteboardShare
    membership = ClassroomMember.objects.filter(user=user).select_related('classroom').first()
    latest_share = None
    if membership:
        latest_share = (
            WhiteboardShare.objects.filter(classroom=membership.classroom)
            .select_related('classroom')
            .first()
        )

    return render(request, 'accounts/dashboard_student.html', {
        'page_title': 'Tableau de bord élève',
        'profile': profile,
        'stats': stats,
        'courses': courses,
        'assignments': assignments,
        'recent_attempts': recent_attempts,
        'user': user,
        'streak': streak,
        'weekly': weekly,
        'recent_badges': recent_badges,
        'active_challenge': active_challenge,
        'latest_share': latest_share,
    })


@teacher_required
def teacher_dashboard(request):
    from classrooms.models import Classroom, ClassroomMember
    from quizzes.models import Quiz, Attempt
    from education.models import Course, Lesson

    user = request.edubac_user
    is_admin = user.is_staff or user.is_superuser
    classrooms_qs = Classroom.objects.all() if is_admin else Classroom.objects.filter(teacher=user)
    memberships = ClassroomMember.objects.all() if is_admin else ClassroomMember.objects.filter(classroom__teacher=user)
    quizzes_qs = Quiz.objects.all() if is_admin else Quiz.objects.filter(created_by=user)
    classrooms = classrooms_qs.annotate(nb_eleves=Count('members'))
    total_students = memberships.values('user').distinct().count()
    my_quizzes = quizzes_qs.annotate(
        nb_q=Count('questions'), nb_att=Count('attempts'),
    ).order_by('-created_at')[:8]
    recent_attempts = Attempt.objects.filter(
        submitted_at__isnull=False,
    ).select_related('student', 'quiz')
    if not is_admin:
        recent_attempts = recent_attempts.filter(
            Q(quiz__created_by=user)
            | Q(student__classroom_memberships__classroom__teacher=user)
        )
    recent_attempts = recent_attempts.distinct().order_by('-submitted_at')[:8]
    avg_score = recent_attempts.aggregate(a=Avg('score'))['a']

    return render(request, 'accounts/dashboard_teacher.html', {
        'page_title': 'Tableau de bord enseignant',
        'classrooms': classrooms,
        'total_students': total_students,
        'my_quizzes': my_quizzes,
        'recent_attempts': recent_attempts,
        'avg_score': round(avg_score, 1) if avg_score else None,
        'courses_count': Course.objects.count(),
        'lessons_count': Lesson.objects.count(),
        'user': user,
    })


@student_required
def my_progress(request):
    from quizzes.models import Attempt
    stats = compute_student_progress(request.edubac_user)
    attempts_qs = Attempt.objects.filter(
        student=request.edubac_user, submitted_at__isnull=False
    ).select_related('quiz').order_by('-submitted_at')
    attempts = list(attempts_qs[:20])
    # Graphique simple (10 derniers scores, ordre chronologique)
    chart_src = list(reversed(list(attempts_qs[:10])))
    chart_scores = []
    for a in chart_src:
        score = float(a.score or 0)
        chart_scores.append({
            'label': a.submitted_at.strftime('%d/%m') if a.submitted_at else '',
            'score': score,
            'height': max(4, min(100, score)),
        })
    return render(request, 'accounts/progress.html', {
        'page_title': 'Ma progression',
        'stats': stats,
        'attempts': attempts,
        'chart_scores': chart_scores,
        'profile': getattr(request.edubac_user, 'student_profile', None),
    })


@student_required
def my_courses(request):
    from education.models import Course
    profile = getattr(request.edubac_user, 'student_profile', None)
    courses = Course.objects.filter(niveau=profile.niveau).order_by('order') if profile else Course.objects.none()
    return render(request, 'accounts/my_courses.html', {
        'page_title': 'Mes cours',
        'courses': courses,
        'profile': profile,
    })


@student_required
def my_lessons(request):
    from education.models import Lesson
    profile = getattr(request.edubac_user, 'student_profile', None)
    lessons = Lesson.objects.none()
    if profile:
        lessons = Lesson.objects.filter(course__niveau=profile.niveau).select_related('course').order_by('course__order', 'order')
    return render(request, 'accounts/my_lessons.html', {
        'page_title': 'Mes leçons',
        'lessons': lessons,
        'profile': profile,
    })


@student_required
def my_favorites(request):
    from accounts.models import FavoriteLesson
    favs = FavoriteLesson.objects.filter(user=request.user).select_related('lesson', 'lesson__course')
    return render(request, 'accounts/favorites.html', {
        'favs': favs,
        'page_title': 'Mes favoris',
    })


@student_required
def calendar_quizzes(request):
    from quizzes.models import QuizAssignment
    from django.utils import timezone
    assignments = (
        QuizAssignment.objects
        .filter(student=request.user)
        .select_related('quiz', 'quiz__lesson')
        .order_by('deadline', '-assigned_at')
    )
    return render(request, 'accounts/calendar.html', {
        'assignments': assignments,
        'today': timezone.localdate(),
        'page_title': 'Calendrier des quiz',
    })


@student_required
def my_badges(request):
    from accounts.engagement import ensure_badges, get_streak, weekly_goal_progress
    from accounts.models import Badge, UserBadge
    ensure_badges()
    earned_ids = set(UserBadge.objects.filter(user=request.user).values_list('badge_id', flat=True))
    badges = Badge.objects.all()
    return render(request, 'accounts/badges.html', {
        'badges': badges,
        'earned_ids': earned_ids,
        'streak': get_streak(request.user),
        'weekly': weekly_goal_progress(request.user),
        'page_title': 'Mes badges',
    })
