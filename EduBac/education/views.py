import mimetypes
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.core.management import call_command
from django.db.models import Count
from .models import Course, Lesson, Resources
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
    from django.urls import reverse
    from .media_library import chapter_relative, course_html_template, documents
    # Contenu public : tous les niveaux sont consultables par tous (visiteur, élève, enseignant),
    # quel que soit le niveau du profil. Seules les fonctions privées (classes, quiz assignés,
    # résultats…) dépendent du compte.
    from cahier.acces import peut_voir
    _ensure_curriculum_loaded()
    meta = next((n for n in CURRICULUM if n['code'] == niveau), None)
    label = meta['label'] if meta else niveau
    course = _course_for_niveau(niveau)
    lessons_qs = course.lessons.all().order_by('order') if course else Lesson.objects.none()
    lessons = []
    for lesson in lessons_qs:
        relative = chapter_relative(lesson)
        html_url = (reverse('education:lesson_course_html', args=[lesson.pk])
                    if course_html_template(lesson, relative=relative) else '')
        lesson_documents = [
            {
                'name': path.name, 'kind': kind,
                'url': reverse('education:lesson_document', args=[lesson.pk, kind, path.name]),
                # « Ouvrir » affiche le cours en ligne quand il existe ; « Télécharger » garde le PDF.
                'open_url': html_url if kind == 'Cours' and html_url else '',
            }
            for kind in ('Cours', 'Exercices')
            for path in documents(lesson, kind, relative=relative)
        ]
        has_file = False
        if lesson.pdf:
            fp = Path(settings.MEDIA_ROOT) / lesson.pdf.name
            has_file = fp.is_file() and fp.stat().st_size > 0
        lessons.append({
            'obj': lesson, 'has_file': has_file,
            'verrouillee': not peut_voir(request, lesson),
            'documents': lesson_documents,
            'course_html_url': html_url,
        })
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


VISIBLES = {'.pdf', '.png', '.jpg', '.jpeg', '.gif', '.webp', '.txt'}   # pas de SVG : il peut contenir du script


def _lecon_verrouillee(request, lesson):
    """Page « Disponible après la séance » si l'élève (ou le visiteur) n'a pas encore accès à la
    leçon ; None sinon. Protège la page, le cours en ligne et chaque fichier (ouvrir ou télécharger)."""
    from cahier.acces import peut_voir
    if peut_voir(request, lesson):
        return None
    return render(request, 'education/lecon_verrouillee.html', {
        'lesson': lesson, 'course': lesson.course, 'page_title': lesson.title,
        'connecte': bool(getattr(request, 'edubac_user', None)),
    }, status=403)


def _acces_classes_du_professeur(request, lesson):
    """Pour le professeur : la leçon est-elle ouverte aux élèves de chacune de ses classes du niveau ?"""
    user = getattr(request, 'edubac_user', None)
    if not user or not user.is_teacher():
        return []
    from cahier.models import AccesLecon
    from classrooms.models import Classroom
    classes = list(Classroom.objects.filter(teacher=user, niveau=lesson.course.niveau).order_by('name'))
    etats = {a.classroom_id: a for a in AccesLecon.objects.filter(lesson=lesson, classroom__in=classes)}
    return [{'classe': c, 'ouverte': bool(etats.get(c.pk) and etats[c.pk].est_ouverte)} for c in classes]


def _documents_lecon(lesson, resources, resource_descriptions, course_html_url):
    """Fichiers des boutons COURS et EXERCICES de la leçon.

    Réunit les PDF rangés dans media/lessons/<niveau>/<leçon>/Cours|Exercices (gestionnaire
    de fichiers) et les documents ajoutés dans l'admin (Leçon › Documents, catégorie Cours ou
    Exercices). « Ouvrir » n'est proposé que pour les formats lisibles dans le navigateur."""
    from .media_library import documents
    root = Path(settings.MEDIA_ROOT).resolve()
    groupes = {'cours': [], 'exercices': []}
    for kind, cle in (('Cours', 'cours'), ('Exercices', 'exercices')):
        for path in documents(lesson, kind):
            url = reverse('education:lesson_document', args=[lesson.pk, kind, path.name])
            ouvrir = course_html_url if (kind == 'Cours' and course_html_url) else url
            groupes[cle].append({
                'titre': path.name, 'extension': 'PDF',
                'description': resource_descriptions.get(path.relative_to(root).as_posix(), ''),
                'ouvrir': ouvrir, 'telecharger': url + '?download=1',
                'en_ligne': ouvrir == course_html_url,
            })
    for resource in resources:
        if resource.categorie not in groupes or not resource.file or not resource.file.name.startswith('resources/'):
            continue
        extension = Path(resource.file.name).suffix.lower()
        url = reverse('education:resource_download', args=[lesson.pk, resource.pk])
        groupes[resource.categorie].append({
            'titre': resource.name, 'extension': extension.lstrip('.').upper() or 'Fichier',
            'description': resource.description,
            'ouvrir': url if extension in VISIBLES else '', 'telecharger': url + '?download=1',
            'en_ligne': False,
        })
    if lesson.pdf:
        url = reverse('education:lesson_pdf', args=[lesson.pk])
        groupes['cours'].append({'titre': Path(lesson.pdf.name).name, 'extension': 'PDF', 'description': '',
                                 'ouvrir': url, 'telecharger': url + '?download=1', 'en_ligne': False})
    if course_html_url and not any(d['en_ligne'] for d in groupes['cours']):
        groupes['cours'].insert(0, {'titre': 'Cours en ligne', 'extension': 'Interactif',
                                    'description': 'Cours paginé, lisible sur ordinateur, téléphone et au vidéoprojecteur.',
                                    'ouvrir': course_html_url, 'telecharger': '', 'en_ligne': True})
    return groupes


def lesson_detail(request, pk):
    lesson = get_object_or_404(Lesson, pk=pk)
    verrou = _lecon_verrouillee(request, lesson)
    if verrou:
        return verrou
    from .media_library import chapter_relative, course_book_data, course_html_template, documents
    course_content_error = ''
    try:
        course_content = lesson.get_content()
    except ValueError as exc:
        course_content = ''
        course_content_error = str(exc)
    course = lesson.course
    resources = list(lesson.resources.all().order_by('ordre', 'name', 'pk'))
    course_html_url = (reverse('education:lesson_course_html', args=[lesson.pk])
                       if course_html_template(lesson) else '')
    resource_descriptions = {
        resource.file.name: resource.description
        for resource in resources
        if resource.file and resource.file.name and resource.description
    }
    chapter_path = chapter_relative(lesson).as_posix()
    markdown_resource = next(
        (
            resource for resource in resources
            if resource.file
            and resource.file.name.startswith(f'{chapter_path}/Cours/')
            and resource.file.name.lower().endswith('.md')
        ),
        None,
    )
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
    docs = _documents_lecon(lesson, resources, resource_descriptions, course_html_url)
    return render(request, 'education/lesson_detail.html', {
        'acces_classes': _acces_classes_du_professeur(request, lesson),
        'lesson': lesson,
        'course_content': course_content,
        'course_content_error': course_content_error,
        'use_course_boxes': (
            course.niveau == '1ere_bac_sc'
            and lesson.order == 2
            and lesson.title == 'Généralités sur les fonctions numériques'
        ),
        'course': course,
        'next_lesson': next_lesson,
        'prev_lesson': prev_lesson,
        'is_fav': is_fav,
        'faq_items': faq_items,
        'docs_boutons': [
            {'cle': cle, 'libelle': libelle, 'titre': titre, 'icone': icone, 'docs': docs[cle]}
            for cle, libelle, titre, icone in (('cours', 'COURS', 'Cours', 'bi-journal-text'),
                                               ('exercices', 'EXERCICES', 'Exercices', 'bi-pencil-square'))
        ],
        'attached_resources': [
            resource for resource in resources
            if resource.file and resource.file.name.startswith('resources/')
            and resource.categorie not in ('cours', 'exercices')
        ],
        'course_html_url': course_html_url,
        'course_book_url': (
            reverse('education:lesson_book_3d', args=[lesson.pk])
            if course_book_data(lesson) else ''
        ),
        'course_markdown_description': (
            markdown_resource.description if markdown_resource else ''
        ),
        'page_title': lesson.title,
    })



def resource_download(request, pk, resource_id):
    """Serve lesson resources through Django instead of exposing MEDIA_ROOT."""
    lesson = get_object_or_404(Lesson, pk=pk)
    resource = get_object_or_404(Resources, pk=resource_id, lesson=lesson)
    relative = Path(resource.file.name)
    if (
        relative.is_absolute()
        or '..' in relative.parts
        or len(relative.parts) < 2
        or relative.parts[0] != 'resources'
    ):
        raise Http404
    verrou = _lecon_verrouillee(request, lesson)
    if verrou:
        return verrou
    root = Path(settings.MEDIA_ROOT).resolve()
    candidate = root / relative
    if candidate.is_symlink():
        raise Http404
    try:
        file_path = candidate.resolve(strict=True)
        if not file_path.is_relative_to(root) or not file_path.is_file():
            raise Http404
        handle = file_path.open('rb')
    except (FileNotFoundError, OSError):
        raise Http404
    filename = file_path.name
    content_type = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
    response = FileResponse(
        handle,
        content_type=content_type,
        as_attachment=file_path.suffix.lower() not in VISIBLES or request.GET.get('download') == '1',
        filename=filename,
    )
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cache-Control'] = 'private, no-store'
    return response


def lesson_document(request, pk, kind, filename):
    from django.http import FileResponse, Http404
    from .media_library import documents
    lesson = get_object_or_404(Lesson, pk=pk)
    if kind not in ('Cours', 'Exercices'):
        raise Http404
    verrou = _lecon_verrouillee(request, lesson)
    if verrou:
        return verrou
    path = next((p for p in documents(lesson, kind) if p.name == filename), None)
    if path is None:
        raise Http404
    try:
        response = FileResponse(path.open('rb'), content_type='application/pdf',
                                as_attachment=request.GET.get('download') == '1',
                                filename=path.name)
    except FileNotFoundError:
        raise Http404
    response['X-Content-Type-Options'] = 'nosniff'
    return response


def lesson_course_html(request, pk):
    """Cours en ligne (HTML) de la leçon ; le PDF reste disponible au téléchargement."""
    from django.http import Http404
    from .media_library import course_book_data, course_html_template
    lesson = get_object_or_404(Lesson.objects.select_related('course'), pk=pk)
    template = course_html_template(lesson)
    if template is None:
        raise Http404
    verrou = _lecon_verrouillee(request, lesson)
    if verrou:
        return verrou
    # Le mode « Présenter » (vidéoprojecteur) est réservé aux professeurs et aux administrateurs.
    is_teacher = getattr(request.user, 'is_teacher', None)
    can_present = bool(request.user.is_authenticated and callable(is_teacher) and is_teacher())
    # Minuteur de la présentation : minutes prévues de chaque bloc (répartition horaire).
    minutage = {}
    if can_present:
        from cahier.rubriques import elements, plan_de_lecon
        minutage = {e['key']: e['minutes'] for e in elements(plan_de_lecon(lesson) or []) if e['minutes']}
    return render(request, template, {
        'lesson': lesson, 'course': lesson.course, 'can_present': can_present, 'minutage': minutage,
        'book_url': reverse('education:lesson_book_3d', args=[lesson.pk]) if course_book_data(lesson) else '',
    })


def lesson_book_3d(request, pk):
    """Livre 3D (Three.js) du cours : leçons à gauche, figures en relief à droite."""
    from .media_library import course_book_data
    lesson = get_object_or_404(Lesson.objects.select_related('course'), pk=pk)
    data = course_book_data(lesson)
    if data is None:
        raise Http404
    verrou = _lecon_verrouillee(request, lesson)
    if verrou:
        return verrou
    return render(request, 'education/cours/livre3d.html', {
        'lesson': lesson, 'course': lesson.course, 'livre': data,
    })


def lesson_pdf(request, pk):
    from django.http import FileResponse, Http404

    lesson = get_object_or_404(Lesson, pk=pk)
    if not lesson.pdf:
        raise Http404
    verrou = _lecon_verrouillee(request, lesson)
    if verrou:
        return verrou
    try:
        handle = lesson.pdf.open('rb')
    except FileNotFoundError:
        raise Http404
    filename = Path(lesson.pdf.name).name
    response = FileResponse(
        handle,
        content_type='application/pdf',
        as_attachment=request.GET.get('download') == '1',
        filename=filename,
    )
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cache-Control'] = 'private, no-store'
    return response


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


def search_quick(request):
    """Recherche rapide (bouton micro flottant) : résultats en JSON pendant la dictée ou la frappe."""
    from django.http import JsonResponse
    from .recherche_rapide import rechercher
    q = (request.GET.get('q') or '').strip()[:200]
    reponse = JsonResponse({'q': q, **rechercher(request, q)})
    reponse['Cache-Control'] = 'private, no-store'
    return reponse


def about(request):
    """Page À propos d'EduBac."""
    return render(request, 'education/about.html', {
        'page_title': 'À propos',
    })


def whiteboard(request):
    """Redirige vers le module Whiteboard."""
    from django.shortcuts import redirect
    return redirect('whiteboard:list')


_ICON_FONT = None


def _splash_assets():
    """Fichiers communs à toutes les pages, téléchargés pendant l'écran de chargement.

    Le service worker les garde : la page suivante s'ouvre vite même avec un
    réseau faible. L'URL de la police d'icônes est celle écrite dans sa feuille
    de style (même entrée de cache).
    """
    import re
    from education.templatetags.edubac_assets import asset_url
    global _ICON_FONT
    if _ICON_FONT is None:
        css = Path(settings.BASE_DIR) / 'static' / 'vendor' / 'bootstrap-icons' / 'bootstrap-icons.min.css'
        try:
            match = re.search(r'url\("?(fonts/bootstrap-icons\.woff2[^")]*)', css.read_text())
        except OSError:
            match = None
        _ICON_FONT = settings.STATIC_URL + 'vendor/bootstrap-icons/' + match.group(1) if match else ''
    files = [
        'vendor/bootstrap/bootstrap.min.css', 'vendor/bootstrap-icons/bootstrap-icons.min.css',
        'css/tokens.css', 'css/edubac.css', 'css/edubac-motion.css', 'css/notebook.css',
        'css/responsive.css', 'css/ui-refresh.css', 'css/pwa.css',
        'vendor/jquery/jquery-3.7.1.min.js', 'vendor/bootstrap/bootstrap.bundle.min.js',
        'js/edubac-ui.js', 'js/edubac-motion.js', 'js/sidebar.js', 'js/notifications.js', 'js/pwa.js',
        'img/welcome-illustration.svg',
    ]
    urls = [asset_url(path) for path in files]
    urls.append(settings.STATIC_URL + 'img/edubac-logo.png')  # utilisé sans version dans la barre
    if _ICON_FONT:
        urls.append(_ICON_FONT)
    return urls


def welcome(request):
    """Écran d'accueil mobile (« Commencer ») affiché avant l'application.

    Aucune redirection côté serveur : la page indique seulement où mener
    l'utilisateur selon sa session actuelle (aucune nouvelle route d'auth).
    """
    from django.urls import reverse
    user = getattr(request, 'edubac_user', None)
    teacher = bool(user and user.is_teacher())
    if not user:
        start = reverse('accounts:login')
    elif user.is_staff or user.is_superuser:
        start = reverse('accounts:admin_dashboard')
    else:
        start = reverse('accounts:dashboard')
    features = [
        {'label': 'Cours', 'icon': 'bi-play-fill', 'tone': 'purple',
         'url': reverse('education:niveaux')},
        {'label': 'Quiz', 'icon': 'bi-clipboard2-check', 'tone': 'teal',
         'url': reverse('quizzes:teacher_ai' if teacher else 'quizzes:assigned')},
        {'label': 'Messages', 'icon': 'bi-chat-dots-fill', 'tone': 'orange',
         'url': reverse('chat:home')},
        {'label': 'Suivi', 'icon': 'bi-graph-up-arrow', 'tone': 'teal',
         'url': reverse('quizzes:teacher_stats' if teacher else 'accounts:progress')},
    ]
    response = render(request, 'education/welcome.html', {
        'start_url': start, 'features': features,
        'splash_assets': _splash_assets(),
    })
    response['Cache-Control'] = 'no-cache'
    return response
