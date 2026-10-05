from django.shortcuts import render, redirect
from django.contrib import messages
from django.views.decorators.http import require_http_methods
from django.db.models import Count, Avg, Q

from .models import User, StudentProfile, TeacherProfile
from .decorators import login_required_simple, student_required, teacher_required
from .services import compute_student_progress


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
    if not user.is_active:
        return None, 'Ce compte est désactivé.'
    return user, None


def _login_session(request, user):
    request.session['user_id'] = user.id
    request.session['role'] = user.role
    request.session.cycle_key()


def login_view(request):
    """
    Login unique : e-mail + mot de passe.
    Le backend détermine le rôle et redirige.
    """
    if getattr(request, 'edubac_user', None):
        return redirect('accounts:dashboard')
    error = None
    if request.method == 'POST':
        user, error = _authenticate(request)
        if user:
            _login_session(request, user)
            messages.success(
                request,
                f'Bienvenue, {user.get_full_name() or user.username} !'
            )
            return redirect('accounts:dashboard')
    return render(request, 'accounts/login.html', {
        'page_title': 'Connexion',
        'error': error,
    })


# Alias : anciennes URLs élève/prof → login unique
def login_student(request):
    return login_view(request)


def login_teacher(request):
    return login_view(request)


def logout_view(request):
    request.session.flush()
    messages.info(request, 'Vous êtes déconnecté.')
    return redirect('education:home')


def register(request):
    """Inscription élève (par défaut publique)."""
    return register_student(request)


def register_choice(request):
    """Plus de choix de rôle : redirige vers inscription élève."""
    return redirect('accounts:register_student')


def register_student(request):
    """
    Inscription élève : Nom, Email, Password, Confirm, Niveau.
    Rôle forcé student côté backend.
    """
    if getattr(request, 'edubac_user', None):
        return redirect('accounts:dashboard')
    error = None
    if request.method == 'POST':
        full_name = (request.POST.get('name') or request.POST.get('full_name') or '').strip()
        first_name = (request.POST.get('first_name') or '').strip()
        last_name = (request.POST.get('last_name') or '').strip()
        if full_name and not (first_name or last_name):
            first_name, last_name = _split_name(full_name)
        email = (request.POST.get('email') or '').strip()
        password = request.POST.get('password') or ''
        password2 = request.POST.get('password2') or ''
        niveau = request.POST.get('niveau', 'tronc_commun')
        valid_niveaux = {c[0] for c in StudentProfile.NIVEAU_CHOICES}
        if niveau not in valid_niveaux:
            niveau = 'tronc_commun'

        if not (first_name or last_name or full_name):
            error = 'Le nom est obligatoire.'
        elif not email or not password:
            error = 'E-mail et mot de passe sont obligatoires.'
        elif password != password2:
            error = 'Les mots de passe ne correspondent pas.'
        elif len(password) < 6:
            error = 'Le mot de passe doit contenir au moins 6 caractères.'
        elif User.objects.filter(email__iexact=email).exists():
            error = 'Cet e-mail est déjà utilisé.'
        else:
            username = _make_username(first_name, last_name, email)
            user = User(
                username=username,
                email=email,
                role='student',  # forcé backend
                first_name=first_name or full_name or email.split('@')[0],
                last_name=last_name,
            )
            user.set_password(password)
            user.save()
            StudentProfile.objects.create(user=user, niveau=niveau)
            _login_session(request, user)
            messages.success(request, 'Compte élève créé. Bienvenue sur EduBac !')
            return redirect('accounts:dashboard')

    return render(request, 'accounts/register_student.html', {
        'page_title': 'Inscription élève',
        'error': error,
        'niveaux': StudentProfile.NIVEAU_CHOICES,
    })


def register_teacher(request):
    """
    Inscription enseignant : Nom, Email, Password, Confirm.
    Aucun code. Rôle forcé teacher côté backend.
    """
    if getattr(request, 'edubac_user', None):
        return redirect('accounts:dashboard')
    error = None
    if request.method == 'POST':
        full_name = (request.POST.get('name') or request.POST.get('full_name') or '').strip()
        first_name = (request.POST.get('first_name') or '').strip()
        last_name = (request.POST.get('last_name') or '').strip()
        if full_name and not (first_name or last_name):
            first_name, last_name = _split_name(full_name)
        email = (request.POST.get('email') or '').strip()
        password = request.POST.get('password') or ''
        password2 = request.POST.get('password2') or ''

        if not (first_name or last_name or full_name):
            error = 'Le nom est obligatoire.'
        elif not email or not password:
            error = 'E-mail et mot de passe sont obligatoires.'
        elif password != password2:
            error = 'Les mots de passe ne correspondent pas.'
        elif len(password) < 6:
            error = 'Le mot de passe doit contenir au moins 6 caractères.'
        elif User.objects.filter(email__iexact=email).exists():
            error = 'Cet e-mail est déjà utilisé.'
        else:
            username = _make_username(first_name, last_name, email)
            user = User(
                username=username,
                email=email,
                role='teacher',  # forcé backend
                first_name=first_name or full_name or email.split('@')[0],
                last_name=last_name,
            )
            user.set_password(password)
            user.save()
            TeacherProfile.objects.create(user=user, subject='Mathématiques')
            _login_session(request, user)
            messages.success(request, 'Compte enseignant créé. Bienvenue !')
            return redirect('accounts:dashboard')

    return render(request, 'accounts/register_teacher.html', {
        'page_title': 'Inscription enseignant',
        'error': error,
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
    if request.edubac_user.role == 'teacher':
        return teacher_dashboard(request)
    return student_dashboard(request)


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
    training_count = Quiz.objects.filter(status='published').count()
    streak = get_streak(user)
    weekly = weekly_goal_progress(user)
    recent_badges = UserBadge.objects.filter(user=user).select_related('badge')[:5]
    from accounts.models import WeeklyChallenge
    from django.utils import timezone
    active_challenge = WeeklyChallenge.objects.filter(
        active=True, start_date__lte=timezone.localdate(), end_date__gte=timezone.localdate()
    ).first()

    return render(request, 'accounts/dashboard_student.html', {
        'page_title': 'Tableau de bord élève',
        'profile': profile,
        'stats': stats,
        'courses': courses,
        'assignments': assignments,
        'recent_attempts': recent_attempts,
        'training_count': training_count,
        'user': user,
        'streak': streak,
        'weekly': weekly,
        'recent_badges': recent_badges,
        'active_challenge': active_challenge,
    })


@teacher_required
def teacher_dashboard(request):
    from classrooms.models import Classroom, ClassroomMember
    from quizzes.models import Quiz, Attempt
    from education.models import Course, Lesson

    user = request.edubac_user
    classrooms = Classroom.objects.filter(teacher=user).annotate(nb_eleves=Count('members'))
    total_students = ClassroomMember.objects.filter(classroom__teacher=user).values('user').distinct().count()
    my_quizzes = Quiz.objects.filter(created_by=user).annotate(
        nb_q=Count('questions'), nb_att=Count('attempts'),
    ).order_by('-created_at')[:8]
    recent_attempts = (
        Attempt.objects
        .filter(Q(quiz__created_by=user) | Q(student__classroom_memberships__classroom__teacher=user))
        .filter(submitted_at__isnull=False)
        .select_related('student', 'quiz')
        .distinct()
        .order_by('-submitted_at')[:8]
    )
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
