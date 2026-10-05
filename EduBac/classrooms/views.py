from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.db.models import Avg, Count, Q
from django.http import FileResponse, HttpResponse, Http404
from django.views.decorators.http import require_POST
from accounts.decorators import login_required_simple, teacher_required, student_required
from .models import Classroom, ClassroomMember
from .services.excel_results import (
    class_excel_path,
    class_has_excel,
    regenerate_class_excel,
    delete_class_excel,
    build_quiz_only_workbook,
)


def _user(request):
    return getattr(request, 'edubac_user', None) or request.user


@teacher_required
def create_classroom(request):
    """Créer une classe (enseignant)."""
    error = None
    if request.method == 'POST':
        name = (request.POST.get('name') or '').strip()
        niveau = request.POST.get('niveau', 'tronc_commun')
        if not name:
            error = 'Le nom de la classe est obligatoire.'
        else:
            classroom = Classroom.objects.create(
                name=name,
                niveau=niveau,
                teacher=request.user,
                is_active=True,
            )
            messages.success(
                request,
                f'Classe « {classroom.name} » créée. Code : {classroom.code}'
            )
            return redirect('classrooms:detail', pk=classroom.pk)
    return render(request, 'classrooms/create.html', {
        'page_title': 'Créer une classe',
        'niveaux': Classroom.NIVEAU_CHOICES,
        'error': error,
    })


@login_required_simple
def classroom_list(request):
    user = _user(request)
    is_teacher = (
        getattr(user, 'role', '') == 'teacher'
        or (hasattr(user, 'is_teacher') and user.is_teacher())
    )
    if is_teacher:
        classrooms = Classroom.objects.filter(teacher=user).annotate(
            nb_eleves=Count('members'),
        )
        return render(request, 'classrooms/list.html', {
            'classrooms': classrooms,
            'page_title': 'Mes classes',
            'is_teacher_view': True,
        })

    # Élève : une seule classe → détail direct, sinon page rejoindre
    membership = (
        ClassroomMember.objects
        .filter(user=user)
        .select_related('classroom')
        .first()
    )
    if membership:
        return redirect('classrooms:detail', pk=membership.classroom_id)
    return redirect('classrooms:join')


@login_required_simple
def join_classroom(request):
    """Élève rejoint UNE seule classe via code (pas plusieurs)."""
    error = None
    user = _user(request)
    if getattr(user, 'role', '') != 'student':
        messages.error(request, 'Seuls les élèves peuvent rejoindre une classe.')
        return redirect('accounts:dashboard')

    # Un élève = une seule classe
    current_membership = (
        ClassroomMember.objects
        .filter(user=user)
        .select_related('classroom')
        .first()
    )
    current_class = current_membership.classroom if current_membership else None

    if request.method == 'POST':
        # Quitter sa classe actuelle
        if request.POST.get('action') == 'leave' and current_membership:
            name = current_class.name
            current_membership.delete()
            messages.info(request, f'Vous avez quitté la classe « {name} ».')
            return redirect('classrooms:join')

        code = (request.POST.get('code') or '').strip().upper()
        if not code:
            error = 'Veuillez entrer le code de la classe.'
        elif current_class:
            error = (
                f'Vous êtes déjà dans la classe « {current_class.name} ». '
                'Un élève ne peut rejoindre qu\'une seule classe. '
                'Quittez-la d\'abord si vous souhaitez changer.'
            )
        else:
            try:
                classroom = Classroom.objects.get(code__iexact=code)
            except Classroom.DoesNotExist:
                error = 'Code incorrect. Vérifiez le code fourni par votre professeur.'
            else:
                if hasattr(classroom, 'is_active') and not classroom.is_active:
                    error = "Cette classe n'est plus active."
                else:
                    try:
                        classroom.add_member(user)
                        messages.success(
                            request,
                            f'Vous avez rejoint la classe « {classroom.name} » avec succès.'
                        )
                        return redirect('classrooms:detail', pk=classroom.pk)
                    except ValueError as e:
                        error = str(e)

    return render(request, 'classrooms/join.html', {
        'page_title': 'Ma classe' if current_class else 'Rejoindre une classe',
        'error': error,
        'current_class': current_class,
    })


@login_required_simple
def classroom_detail(request, pk):
    user = _user(request)
    classroom = get_object_or_404(Classroom, pk=pk)
    is_teacher_owner = (
        getattr(user, 'role', '') == 'teacher'
        and classroom.teacher_id == getattr(user, 'id', None)
    )
    is_member = ClassroomMember.objects.filter(classroom=classroom, user=user).exists()
    if not is_teacher_owner and not is_member and not getattr(user, 'is_superuser', False):
        messages.error(request, 'Accès non autorisé à cette classe.')
        return redirect('classrooms:list')

    members = classroom.members.select_related('user', 'user__student_profile')
    nb_eleves = members.count()

    # Stats quiz / résultats pour le propriétaire
    quiz_stats = []
    nb_quiz = 0
    nb_results = 0
    if is_teacher_owner:
        from quizzes.models import Attempt, Quiz
        student_ids = list(members.values_list('user_id', flat=True))
        attempts = Attempt.objects.filter(
            student_id__in=student_ids,
            submitted_at__isnull=False,
        ).select_related('quiz')
        nb_results = attempts.count()
        # Group by quiz
        quiz_ids = attempts.values_list('quiz_id', flat=True).distinct()
        quizzes = Quiz.objects.filter(pk__in=quiz_ids).order_by('-created_at')
        nb_quiz = quizzes.count()
        for q in quizzes:
            q_atts = attempts.filter(quiz=q)
            avg = q_atts.aggregate(a=Avg('score'))['a']
            quiz_stats.append({
                'quiz': q,
                'count': q_atts.count(),
                'avg': round(avg, 1) if avg is not None else None,
            })

    return render(request, 'classrooms/detail.html', {
        'classroom': classroom,
        'members': members,
        'is_teacher_owner': is_teacher_owner,
        'nb_eleves': nb_eleves,
        'nb_quiz': nb_quiz,
        'nb_results': nb_results,
        'quiz_stats': quiz_stats,
        'has_excel': class_has_excel(classroom) if is_teacher_owner else False,
        'page_title': classroom.name,
    })


@teacher_required
def edit_classroom(request, pk):
    """Modifier nom / niveau d'une classe (propriétaire uniquement)."""
    classroom = get_object_or_404(Classroom, pk=pk, teacher=request.user)
    error = None
    if request.method == 'POST':
        name = (request.POST.get('name') or '').strip()
        niveau = request.POST.get('niveau', classroom.niveau)
        if not name:
            error = 'Le nom de la classe est obligatoire.'
        else:
            classroom.name = name
            classroom.niveau = niveau
            classroom.save(update_fields=['name', 'niveau'])
            messages.success(request, f'Classe « {classroom.name} » mise à jour.')
            return redirect('classrooms:detail', pk=classroom.pk)
    return render(request, 'classrooms/edit.html', {
        'classroom': classroom,
        'niveaux': Classroom.NIVEAU_CHOICES,
        'error': error,
        'page_title': f'Modifier — {classroom.name}',
    })


@teacher_required
def delete_classroom(request, pk):
    """
    Suppression d'une classe (POST + CSRF uniquement).
    Ne supprime JAMAIS les comptes élèves — uniquement Classroom + ClassroomMember.
    Option : supprimer aussi le fichier Excel.
    """
    classroom = get_object_or_404(Classroom, pk=pk, teacher=request.user)

    members_count = classroom.members.count()
    from quizzes.models import Attempt
    student_ids = list(
        ClassroomMember.objects.filter(classroom=classroom).values_list('user_id', flat=True)
    )
    results_count = Attempt.objects.filter(
        student_id__in=student_ids, submitted_at__isnull=False
    ).count()
    # Quiz distincts ayant des résultats dans cette classe
    quiz_count = (
        Attempt.objects.filter(student_id__in=student_ids, submitted_at__isnull=False)
        .values('quiz_id')
        .distinct()
        .count()
    )
    has_excel = class_has_excel(classroom)

    if request.method == 'POST':
        # Double vérification propriétaire
        if classroom.teacher_id != request.user.id and not request.user.is_superuser:
            messages.error(request, 'Vous ne pouvez supprimer que vos propres classes.')
            return redirect('classrooms:list')

        delete_excel = request.POST.get('delete_excel') == 'on'
        name = classroom.name

        if delete_excel:
            delete_class_excel(classroom)

        # CASCADE sur ClassroomMember uniquement — User non touché
        classroom.delete()
        messages.success(
            request,
            f'Classe « {name} » supprimée. Les comptes élèves sont conservés.'
        )
        return redirect('classrooms:list')

    return render(request, 'classrooms/delete_confirm.html', {
        'classroom': classroom,
        'members_count': members_count,
        'quiz_count': quiz_count,
        'results_count': results_count,
        'has_excel': has_excel,
        'page_title': f'Supprimer — {classroom.name}',
    })


@teacher_required
def remove_member(request, pk, user_id):
    """Retirer un élève de la classe."""
    classroom = get_object_or_404(Classroom, pk=pk, teacher=request.user)
    if request.method == 'POST':
        ClassroomMember.objects.filter(classroom=classroom, user_id=user_id).delete()
        messages.success(request, 'Élève retiré de la classe.')
    return redirect('classrooms:detail', pk=classroom.pk)


@teacher_required
def toggle_classroom_active(request, pk):
    """Activer / archiver une classe."""
    classroom = get_object_or_404(Classroom, pk=pk, teacher=request.user)
    if request.method == 'POST':
        classroom.is_active = not classroom.is_active
        classroom.save(update_fields=['is_active'])
        if classroom.is_active:
            messages.success(request, f'Classe « {classroom.name} » réactivée.')
        else:
            messages.info(request, f'Classe « {classroom.name} » archivée (inactive).')
    return redirect('classrooms:detail', pk=classroom.pk)


@teacher_required
def my_students(request):
    """Tous les élèves des classes de l'enseignant."""
    memberships = (
        ClassroomMember.objects
        .filter(classroom__teacher=request.user)
        .select_related('user', 'user__student_profile', 'classroom')
        .order_by('user__last_name', 'user__first_name')
    )
    seen = set()
    students = []
    for m in memberships:
        if m.user_id not in seen:
            seen.add(m.user_id)
            students.append(m)
    return render(request, 'classrooms/students.html', {
        'memberships': students,
        'page_title': 'Mes élèves',
    })


@teacher_required
def classroom_results(request, pk):
    """Page des résultats d'une classe (stats par quiz + liens Excel)."""
    classroom = get_object_or_404(Classroom, pk=pk, teacher=request.user)
    from quizzes.models import Attempt, Quiz

    student_ids = list(
        ClassroomMember.objects.filter(classroom=classroom).values_list('user_id', flat=True)
    )
    attempts = (
        Attempt.objects.filter(student_id__in=student_ids, submitted_at__isnull=False)
        .select_related('student', 'quiz', 'quiz__lesson')
    )
    nb_eleves = len(student_ids)
    quiz_ids = attempts.values_list('quiz_id', flat=True).distinct()
    quizzes = Quiz.objects.filter(pk__in=quiz_ids).order_by('-created_at')

    quiz_rows = []
    for q in quizzes:
        q_atts = attempts.filter(quiz=q)
        avg = q_atts.aggregate(a=Avg('score'))['a']
        quiz_rows.append({
            'quiz': q,
            'nb_eleves': q_atts.values('student_id').distinct().count(),
            'nb_attempts': q_atts.count(),
            'avg': round(avg, 1) if avg is not None else None,
            'avg_note': round(avg / 5, 1) if avg is not None else None,
        })

    return render(request, 'classrooms/results.html', {
        'classroom': classroom,
        'nb_eleves': nb_eleves,
        'nb_quiz': len(quiz_rows),
        'quiz_rows': quiz_rows,
        'has_excel': class_has_excel(classroom),
        'page_title': f'Résultats — {classroom.name}',
    })


@teacher_required
def download_class_excel(request, pk):
    """Télécharger le fichier Excel complet de la classe (régénéré depuis la DB)."""
    classroom = get_object_or_404(Classroom, pk=pk, teacher=request.user)
    # Toujours régénérer depuis la DB (source de vérité)
    path = regenerate_class_excel(classroom)
    if not path.exists():
        messages.error(request, 'Impossible de générer le fichier Excel.')
        return redirect('classrooms:results', pk=classroom.pk)

    safe_name = classroom.name.replace(' ', '_')[:40]
    response = FileResponse(
        open(path, 'rb'),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="Classe_{safe_name}.xlsx"'
    return response


@teacher_required
def download_quiz_excel(request, pk, quiz_id):
    """Télécharger un Excel ne contenant que les résultats d'un quiz pour la classe."""
    from quizzes.models import Quiz
    classroom = get_object_or_404(Classroom, pk=pk, teacher=request.user)
    quiz = get_object_or_404(Quiz, pk=quiz_id)

    wb = build_quiz_only_workbook(classroom, quiz)
    from io import BytesIO
    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    safe_class = classroom.name.replace(' ', '_')[:30]
    safe_quiz = quiz.title.replace(' ', '_')[:30]
    filename = f'Resultats_{safe_quiz}_{safe_class}.xlsx'

    response = HttpResponse(
        buffer.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@teacher_required
def regenerate_excel(request, pk):
    """Force la régénération du fichier Excel depuis la base Django."""
    classroom = get_object_or_404(Classroom, pk=pk, teacher=request.user)
    if request.method == 'POST':
        try:
            regenerate_class_excel(classroom)
            messages.success(request, 'Fichier Excel régénéré à partir de la base de données.')
        except Exception as e:
            messages.error(request, f'Erreur lors de la régénération : {e}')
    return redirect('classrooms:results', pk=classroom.pk)
