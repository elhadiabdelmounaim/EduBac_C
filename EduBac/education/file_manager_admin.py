"""Django Admin view for organizing lesson documents without moving old files."""

from urllib.parse import urlencode

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse

from .file_manager import (
    CATEGORY_CONFIG,
    FileManagerError,
    category_catalogue,
    delete_managed_file,
    existing_items,
    lesson_catalogue,
    save_upload,
)
from .file_manager_forms import FileManagerForm
from .models import Course, Lesson, Resources


def _manager_url(query=None):
    url = reverse('admin:education_course_file_manager')
    query = {key: value for key, value in (query or {}).items() if value}
    return f'{url}?{urlencode(query)}' if query else url


def _selected_values(request, form):
    if request.method == 'POST' and form is not None:
        level = form['niveau'].value()
        lesson_id = form['lecon'].value()
        category = form['categorie'].value()
    else:
        level = request.GET.get('niveau', '')
        lesson_id = request.GET.get('lecon', '')
        category = request.GET.get('categorie', '')
    return level or '', str(lesson_id or ''), category or ''


def file_manager_view(request, model_admin):
    resources_admin = model_admin.admin_site._registry.get(Resources)
    if (
        not model_admin.has_change_permission(request)
        or resources_admin is None
        or not resources_admin.has_change_permission(request)
    ):
        raise PermissionDenied

    form = None
    if request.method == 'POST' and request.POST.get('action') == 'delete':
        lesson = Lesson.objects.filter(pk=request.POST.get('lecon')).select_related(
            'course'
        ).first()
        category = request.POST.get('categorie', '')
        query = {
            'niveau': lesson.course.niveau if lesson else '',
            'lecon': lesson.pk if lesson else '',
            'categorie': category,
        }
        if not lesson or category not in CATEGORY_CONFIG:
            messages.error(request, 'La leçon ou la catégorie sélectionnée n’est plus disponible.')
        elif request.POST.get('confirmer_suppression') != 'yes':
            messages.error(request, 'Cochez la confirmation avant de supprimer ce fichier.')
        else:
            try:
                relative_path = delete_managed_file(
                    lesson,
                    category,
                    filename=request.POST.get('filename', ''),
                    resource_id=request.POST.get('resource_id') or None,
                    admin_user_id=request.user.pk,
                )
            except FileManagerError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(
                    request,
                    f'Fichier supprimé : media/{relative_path}',
                )
        return redirect(_manager_url(query))

    if request.method == 'POST':
        form = FileManagerForm(request.POST, request.FILES)
        if form.is_valid():
            lesson = form.cleaned_data['lecon']
            category = form.cleaned_data['categorie']
            try:
                result = save_upload(
                    lesson,
                    category,
                    form.cleaned_data['titre'],
                    form.cleaned_data['fichier'],
                    confirm_replace=form.cleaned_data['confirmer_remplacement'],
                    replacement_selection=form.cleaned_data['remplacer_fichier'],
                )
            except FileManagerError as exc:
                form.add_error('fichier', str(exc))
            else:
                if result['status'] == 'duplicate':
                    messages.warning(
                        request,
                        'Aucun doublon n’a été créé. Un fichier identique existe déjà : '
                        f"media/{result['path']}",
                    )
                elif result['status'] == 'replaced':
                    messages.success(
                        request,
                        f"Fichier remplacé : media/{result['path']}",
                    )
                else:
                    messages.success(
                        request,
                        f"Fichier importé : media/{result['path']}",
                    )
                return redirect(_manager_url({
                    'niveau': lesson.course.niveau,
                    'lecon': lesson.pk,
                    'categorie': category,
                }))

    level, lesson_id, category = _selected_values(request, form)
    selected_lesson = (
        Lesson.objects.select_related('course').filter(pk=lesson_id).first()
        if lesson_id.isdigit()
        else None
    )
    if selected_lesson:
        level = selected_lesson.course.niveau
    if category not in CATEGORY_CONFIG:
        category = ''

    items = (
        existing_items(selected_lesson, category)
        if selected_lesson and category
        else []
    )
    replacement_targets = [
        {
            'value': (
                f"resource:{item['resource_id']}"
                if item['resource_id']
                else f"file:{item['filename']}"
            ),
            'path': item['relative_path'],
        }
        for item in items
    ]
    if form is None:
        form = FileManagerForm(initial={
            'niveau': level,
            'lecon': selected_lesson.pk if selected_lesson else '',
            'categorie': category,
        })

    context = model_admin.admin_site.each_context(request)
    context.update({
        'title': 'Gestionnaire intelligent des fichiers',
        'opts': Course._meta,
        'form': form,
        'lesson_catalogue': lesson_catalogue(),
        'category_catalogue': category_catalogue(),
        'selected_level': level,
        'selected_lesson': selected_lesson,
        'selected_category': category,
        'selected_category_label': (
            CATEGORY_CONFIG[category]['label'] if category else ''
        ),
        'selected_folder': (
            CATEGORY_CONFIG[category]['folder']
            if category and CATEGORY_CONFIG[category]['folder']
            else None
        ),
        'existing_items': items,
        'replacement_targets': replacement_targets,
        'manager_url': reverse('admin:education_course_file_manager'),
        'replacement_options_url': reverse(
            'admin:education_course_file_manager_replacements'
        ),
        'course_changelist_url': reverse('admin:education_course_changelist'),
        'max_upload_mb': 20,
    })
    return TemplateResponse(request, 'admin/education/file_manager.html', context)


def replacement_options_view(request, model_admin):
    """Return only replaceable files belonging to the selected lesson/category."""
    resources_admin = model_admin.admin_site._registry.get(Resources)
    if (
        not model_admin.has_view_permission(request)
        or resources_admin is None
        or not resources_admin.has_view_permission(request)
    ):
        raise PermissionDenied

    lesson_id = request.GET.get('lecon')
    category = request.GET.get('categorie')
    if category not in CATEGORY_CONFIG:
        return JsonResponse({'options': []})
    lesson = Lesson.objects.filter(pk=lesson_id).first()
    if not lesson:
        return JsonResponse({'options': []})
    options = []
    for item in existing_items(lesson, category):
        value = (
            f"resource:{item['resource_id']}"
            if item['resource_id']
            else f"file:{item['filename']}"
        )
        options.append({
            'value': value,
            'label': item['name'],
            'path': item['relative_path'],
        })
    return JsonResponse({'options': options})
