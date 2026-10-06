from django.shortcuts import render, get_object_or_404, redirect
from django.core.exceptions import ObjectDoesNotExist
from django.core.management import call_command
from django.db.models import Count
from .models import Course, Lesson
from .curriculum import CURRICULUM



def _ensure_curriculum_loaded():
    """Complète le catalogue depuis sa source de référence sans écraser les leçons."""
    expected = {
        level['code']: len(level['lessons'])
        for level in CURRICULUM
    }
    existing_counts = dict(
        Course.objects
        .filter(name='Mathématiques', niveau__in=expected)
        .values('niveau')
        .annotate(lesson_count=Count('lessons'))
        .values_list('niveau', 'lesson_count')
    )
    if any(
        existing_counts.get(code, 0) < expected_count
        for code, expected_count in expected.items()
    ):
        call_command('load_curriculum', verbosity=0)


def _course_for_niveau(niveau):
    """Privilégie le cours canonique alimenté par load_curriculum."""
    return (
        Course.objects.filter(niveau=niveau, name='Mathématiques').first()
        or Course.objects.filter(niveau=niveau).first()
    )


def niveaux_list(request):
    """Page Niveau scolaire — cartes de tous les niveaux."""
    from .curriculum import STUDENT_LEVELS
    _ensure_curriculum_loaded()
    levels = []
    for item in STUDENT_LEVELS:
        code = item.get('maps_to') or item['code']
        course = _course_for_niveau(code)
        lesson_count = course.lessons.count() if course else 0
        levels.append({
            **item,
            'course': course,
            'lesson_count': lesson_count,
            'link_code': code,
        })
    return render(request, 'education/niveaux_list.html', {
        'levels': levels,
        'page_title': 'Niveau scolaire',
    })


def home(request):
    """
    Page d'accueil : les niveaux avec leurs leçons dans l'ordre académique.
    """
    _ensure_curriculum_loaded()
    niveaux = []
    for n in CURRICULUM:
        course = _course_for_niveau(n['code'])
        lessons = []
        if course:
            lessons = list(course.lessons.all().order_by('order'))
        niveaux.append({
            'code': n['code'],
            'label': n['label'],
            'order': n['order'],
            'color': n.get('color', 'teal'),
            'course': course,
            'lessons': lessons,
            'count': len(lessons),
        })
    return render(request, 'education/home.html', {
        'niveaux': niveaux,
        'page_title': 'Accueil',
    })


def niveau_detail(request, niveau):
    """Détail d'un niveau : toutes les leçons + bouton Accéder au cours."""
    from pathlib import Path
    from django.conf import settings
    from django.contrib import messages
    # Sécurité : un élève ne voit que son niveau (sauf lecture libre si non connecté)
    user = getattr(request, 'edubac_user', None) or getattr(request, 'user', None)
    if user and getattr(user, 'is_authenticated', False) and getattr(user, 'role', None) == 'student':
        try:
            student_profile = user.student_profile
        except (AttributeError, ObjectDoesNotExist):
            student_profile = None
        if student_profile:
            student_niveau = student_profile.niveau
            effective_niveau = {
                'tronc_commun_lettres': 'tronc_commun',
            }.get(niveau, niveau)
            if effective_niveau != student_niveau:
                messages.warning(
                    request,
                    "Ce niveau n'est pas associé à votre compte. "
                    f"Votre niveau : {student_profile.get_niveau_display()}."
                )
                return redirect('education:niveau_detail', niveau=student_niveau)
    _ensure_curriculum_loaded()
    meta = next((n for n in CURRICULUM if n['code'] == niveau), None)
    label = meta['label'] if meta else niveau
    course = _course_for_niveau(niveau)
    lessons_qs = course.lessons.all().order_by('order') if course else Lesson.objects.none()
    lessons = []
    for lesson in lessons_qs:
        has_file = False
        if lesson.pdf:
            fp = Path(settings.MEDIA_ROOT) / lesson.pdf.name
            has_file = fp.is_file() and fp.stat().st_size > 0
        lessons.append({'obj': lesson, 'has_file': has_file})
    return render(request, 'education/niveau_detail.html', {
        'niveau_code': niveau,
        'niveau_label': label,
        'course': course,
        'lessons': lessons,
        'page_title': label,
    })


def course_detail(request, pk):
    course = get_object_or_404(Course, pk=pk)
    lessons = course.get_lessons()
    return render(request, 'education/course_detail.html', {
        'course': course,
        'lessons': lessons,
        'page_title': course.name,
    })


def lesson_detail(request, pk):
    lesson = get_object_or_404(Lesson, pk=pk)
    course = lesson.course
    # Leçon suivante / précédente
    next_lesson = Lesson.objects.filter(course=course, order__gt=lesson.order).order_by('order').first()
    prev_lesson = Lesson.objects.filter(course=course, order__lt=lesson.order).order_by('-order').first()
    is_fav = False
    if getattr(request, 'user', None) and request.user.is_authenticated:
        from accounts.models import FavoriteLesson
        is_fav = FavoriteLesson.objects.filter(user=request.user, lesson=lesson).exists()
        if request.method == 'POST' and request.POST.get('action') == 'toggle_fav':
            if is_fav:
                FavoriteLesson.objects.filter(user=request.user, lesson=lesson).delete()
                is_fav = False
            else:
                FavoriteLesson.objects.get_or_create(user=request.user, lesson=lesson)
                is_fav = True
    # FAQ parse
    faq_items = []
    if lesson.faq:
        for line in lesson.faq.splitlines():
            line = line.strip()
            if not line:
                continue
            if '|' in line:
                q, a = line.split('|', 1)
                faq_items.append({'q': q.strip(), 'a': a.strip()})
            else:
                faq_items.append({'q': line, 'a': ''})
    return render(request, 'education/lesson_detail.html', {
        'lesson': lesson,
        'course': course,
        'next_lesson': next_lesson,
        'prev_lesson': prev_lesson,
        'is_fav': is_fav,
        'faq_items': faq_items,
        'page_title': lesson.title,
    })



def search(request):
    """Recherche cours et leçons par mot-clé."""
    q = (request.GET.get('q') or '').strip()
    courses = []
    lessons = []
    if q:
        from django.db.models import Q
        courses = list(Course.objects.filter(
            Q(name__icontains=q) | Q(description__icontains=q)
        ).order_by('niveau', 'order')[:20])
        lessons = list(Lesson.objects.filter(
            Q(title__icontains=q) | Q(content__icontains=q)
        ).select_related('course').order_by('course__niveau', 'order')[:30])
    return render(request, 'education/search.html', {
        'q': q,
        'courses': courses,
        'lessons': lessons,
        'page_title': 'Recherche',
    })


def about(request):
    """Page À propos d'EduBac."""
    return render(request, 'education/about.html', {
        'page_title': 'À propos',
    })


def whiteboard(request):
    """Redirige vers le module Whiteboard."""
    from django.shortcuts import redirect
    return redirect('whiteboard:list')
