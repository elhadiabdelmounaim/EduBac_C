from datetime import timedelta

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.utils import timezone
from django.db.models import Avg, Count, Q
from django.db import transaction
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


# Un utilisateur est « actif » s'il a utilisé l'application dans les 5 dernières minutes.
ACTIF_DEPUIS = timedelta(minutes=5)


def _user(request):
    return getattr(request, 'edubac_user', None) or request.user


def _is_admin(user):
    return bool(getattr(user, 'is_staff', False) or getattr(user, 'is_superuser', False))


def _managed_classrooms(user):
    if _is_admin(user):
        return Classroom.objects.all()
    return Classroom.objects.filter(teacher=user)


def _managed_classroom(user, pk):
    return get_object_or_404(_managed_classrooms(user), pk=pk)


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
    is_teacher = hasattr(user, 'is_teacher') and user.is_teacher()
    if is_teacher:
        classrooms = _managed_classrooms(user).annotate(
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
        _is_admin(user)
        or (
            getattr(user, 'role', '') == 'teacher'
            and classroom.teacher_id == getattr(user, 'id', None)
        )
    )
    membership = ClassroomMember.objects.filter(
        classroom=classroom,
        user=user,
    ).first()
    is_member = membership is not None
    if not is_teacher_owner and not is_member:
        messages.error(request, 'Accès non autorisé à cette classe.')
        return redirect('classrooms:list')

    members = classroom.members.select_related('user', 'user__student_profile')
    nb_eleves = members.count()

    # Administrateur seulement : qui est actif dans l'application en ce moment.
    voir_presence = _is_admin(user)
    nb_actifs = 0
    if voir_presence:
        limite = timezone.now() - ACTIF_DEPUIS
        members = list(members)
        for m in members:
            vu = m.user.derniere_activite
            m.est_actif = bool(vu and vu >= limite)
        nb_actifs = sum(m.est_actif for m in members)
        # Les actifs d'abord, puis du plus récemment vu au plus ancien (jamais vus à la fin).
        members.sort(key=lambda m: (not m.est_actif, -(m.user.derniere_activite.timestamp()
                                                         if m.user.derniere_activite else 0)))

    # Stats quiz / résultats pour le propriétaire
    quiz_stats = []
    nb_quiz = 0
    nb_results = 0
    if is_teacher_owner:
        from quizzes.models import Attempt, Quiz
        student_ids = [m.user_id for m in members]
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
        'membership': membership,
        'members': members,
        'is_teacher_owner': is_teacher_owner,
        'nb_eleves': nb_eleves,
        'nb_quiz': nb_quiz,
        'nb_results': nb_results,
        'quiz_stats': quiz_stats,
        'voir_presence': voir_presence,
        'nb_actifs': nb_actifs,
        'actif_minutes': int(ACTIF_DEPUIS.total_seconds() // 60),
        'has_excel': class_has_excel(classroom) if is_teacher_owner else False,
        'page_title': classroom.name,
    })


@teacher_required
def edit_classroom(request, pk):
    """Modifier nom / niveau d'une classe (propriétaire uniquement)."""
    classroom = _managed_classroom(request.user, pk)
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
    classroom = _managed_classroom(request.user, pk)

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
        if classroom.teacher_id != request.user.id and not _is_admin(request.user):
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
@require_POST
def reject_members(request, pk=None):
    """Supprimer uniquement les adhésions sélectionnées dans les classes du professeur."""
    classroom = _managed_classroom(request.user, pk) if pk else None
    destination = (
        redirect('classrooms:detail', pk=classroom.pk)
        if classroom else redirect('classrooms:students')
    )
    raw_ids = request.POST.getlist('membership_ids')
    if not raw_ids:
        messages.error(request, 'Sélectionnez au moins un élève.')
        return destination
    try:
        ids = {int(value) for value in raw_ids}
    except (ValueError, TypeError):
        raise Http404('Sélection invalide.')
    with transaction.atomic():
        memberships = ClassroomMember.objects.select_for_update().filter(
            pk__in=ids, user__role='student',
        )
        if not _is_admin(request.user):
            memberships = memberships.filter(classroom__teacher=request.user)
        if classroom:
            memberships = memberships.filter(classroom=classroom)
        # Refuser toute la sélection si elle contient un membre hors de ce périmètre.
        selected = list(memberships.values_list('pk', flat=True))
        if set(selected) != ids:
            raise Http404('Un élève sélectionné ne fait pas partie de cette liste.')
        ClassroomMember.objects.filter(pk__in=selected).delete()
    messages.success(
        request,
        f'{len(selected)} élève(s) retiré(s) de la classe. Comptes et résultats conservés.',
    )
    return destination


@teacher_required
def remove_member(request, pk, user_id):
    """Retirer un élève de la classe."""
    classroom = _managed_classroom(request.user, pk)
    if request.method == 'POST':
        ClassroomMember.objects.filter(classroom=classroom, user_id=user_id).delete()
        messages.success(request, 'Élève retiré de la classe.')
    return redirect('classrooms:detail', pk=classroom.pk)


@teacher_required
def toggle_classroom_active(request, pk):
    """Activer / archiver une classe."""
    classroom = _managed_classroom(request.user, pk)
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
    memberships_qs = ClassroomMember.objects.all()
    if not _is_admin(request.user):
        memberships_qs = memberships_qs.filter(classroom__teacher=request.user)
    memberships = (
        memberships_qs
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
    classroom = _managed_classroom(request.user, pk)
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
    classroom = _managed_classroom(request.user, pk)
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
    classroom = _managed_classroom(request.user, pk)
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
    classroom = _managed_classroom(request.user, pk)
    if request.method == 'POST':
        try:
            regenerate_class_excel(classroom)
            messages.success(request, 'Fichier Excel régénéré à partir de la base de données.')
        except Exception as e:
            messages.error(request, f'Erreur lors de la régénération : {e}')
    return redirect('classrooms:results', pk=classroom.pk)


@teacher_required
def rapport_semaine(request):
    """Rapport des 7 derniers jours, classe par classe (le même que celui du dimanche)."""
    from .rapport import rapport_professeur
    return render(request, 'classrooms/rapport.html', {
        'rapport': rapport_professeur(request.edubac_user),
        'page_title': 'Rapport de la semaine',
    })


# ─── Carnet de notes ─────────────────────────────────────────────────────────

@teacher_required
def carnet_index(request):
    """Le carnet de la première classe ; les autres sont accessibles par des onglets."""
    classe = _managed_classrooms(_user(request)).filter(is_active=True).order_by('niveau', 'name').first()
    if classe is None:
        messages.info(request, 'Créez d’abord une classe.')
        return redirect('classrooms:list')
    return redirect('classrooms:carnet', classe.pk)


@teacher_required
def carnet(request, pk):
    from decimal import Decimal, InvalidOperation
    from . import notes
    from .models import ColonneNote
    user = _user(request)
    classe = _managed_classroom(user, pk)
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'ajouter':
            source = request.POST.get('source')
            colonne = ColonneNote(classe=classe, ordre=classe.colonnes_notes.count())
            if source == ColonneNote.DEVOIR:
                from devoirs.models import Devoir
                colonne.devoir = get_object_or_404(Devoir, pk=request.POST.get('devoir'), classes=classe)
                colonne.source, colonne.titre = ColonneNote.DEVOIR, colonne.devoir.titre[:120]
            elif source == ColonneNote.QUIZ:
                from quizzes.models import Quiz
                colonne.quiz = get_object_or_404(Quiz, pk=request.POST.get('quiz'))
                colonne.source, colonne.titre = ColonneNote.QUIZ, colonne.quiz.title[:120]
            else:
                colonne.titre = (request.POST.get('titre') or '').strip()[:120] or 'Contrôle'
            colonne.save()
            messages.success(request, f'Colonne « {colonne.titre} » ajoutée.')
        elif action in ('regler', 'supprimer'):
            colonne = get_object_or_404(ColonneNote, pk=request.POST.get('colonne'), classe=classe)
            if action == 'supprimer':
                colonne.delete()
                messages.success(request, f'Colonne « {colonne.titre} » supprimée.')
            else:
                try:
                    coef = Decimal((request.POST.get('coefficient') or '1').replace(',', '.'))
                    if not (0 < coef <= 20):
                        raise InvalidOperation
                except InvalidOperation:
                    messages.error(request, 'Le coefficient doit être un nombre entre 0 et 20.')
                    return redirect('classrooms:carnet', classe.pk)
                colonne.titre = (request.POST.get('titre') or colonne.titre).strip()[:120]
                colonne.coefficient = coef
                colonne.dans_moyenne = request.POST.get('dans_moyenne') == '1'
                colonne.visible_eleves = request.POST.get('visible_eleves') == '1'
                colonne.save()
                messages.success(request, 'Colonne mise à jour.')
        return redirect('classrooms:carnet', classe.pk)
    devoirs, quiz = notes.suggestions(classe)
    return render(request, 'classrooms/carnet.html', {
        'classe': classe, 't': notes.tableau(classe), 'devoirs_libres': devoirs, 'quiz_libres': quiz,
        'classes': _managed_classrooms(user).filter(is_active=True).order_by('niveau', 'name'),
        'page_title': f'Carnet de notes — {classe.name}',
    })


@require_POST
@teacher_required
def carnet_note(request, pk):
    """Enregistre une note saisie (JSON) et renvoie la nouvelle moyenne de l'élève."""
    import json
    from decimal import Decimal, InvalidOperation
    from django.http import JsonResponse
    from . import notes
    from .models import ColonneNote, NoteSaisie
    classe = _managed_classroom(_user(request), pk)
    try:
        data = json.loads(request.body.decode('utf-8') or '{}')
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'Requête invalide.'}, status=400)
    colonne = get_object_or_404(ColonneNote, pk=data.get('colonne'), classe=classe, source=ColonneNote.MANUEL)
    if not ClassroomMember.objects.filter(classroom=classe, user_id=data.get('eleve')).exists():
        return JsonResponse({'error': 'Élève inconnu dans cette classe.'}, status=404)
    brut = str(data.get('note') or '').strip().replace(',', '.')
    try:
        note = Decimal(brut) if brut else None
        if note is not None and not (0 <= note <= 20):
            raise InvalidOperation
    except InvalidOperation:
        return JsonResponse({'error': 'Note entre 0 et 20.'}, status=400)
    NoteSaisie.objects.update_or_create(colonne=colonne, eleve_id=data['eleve'], defaults={'note': note})
    t = notes.tableau(classe)
    moyenne = next((l['moyenne'] for l in t['lignes'] if str(l['eleve'].pk) == str(data['eleve'])), None)
    colonne_calculee = next(c for c in t['colonnes'] if c.pk == colonne.pk)
    return JsonResponse({'ok': True, 'note': notes.texte(note), 'moyenne': notes.texte(moyenne),
                         'moyenne_colonne': colonne_calculee.moyenne_texte, 'moyenne_classe': t['moyenne_classe_texte']})


@teacher_required
def carnet_excel(request, pk):
    from io import BytesIO
    from django.utils.text import slugify
    from . import notes
    classe = _managed_classroom(_user(request), pk)
    tampon = BytesIO()
    notes.classeur_excel(classe).save(tampon)
    reponse = HttpResponse(tampon.getvalue(),
                           content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    reponse['Content-Disposition'] = f'attachment; filename="carnet-{slugify(classe.name) or classe.pk}.xlsx"'
    return reponse


@student_required
def mes_notes(request):
    """Les notes de l'élève, colonnes rendues visibles par le professeur, classe par classe."""
    from . import notes
    user = _user(request)
    carnets = []
    for m in ClassroomMember.objects.filter(user=user, classroom__is_active=True).select_related('classroom'):
        t = notes.tableau(m.classroom, pour_eleve=user)
        if t['colonnes']:
            carnets.append({'classe': m.classroom, 'ligne': t['lignes'][0], 'colonnes': t['colonnes']})
    return render(request, 'classrooms/mes_notes.html', {'carnets': carnets, 'page_title': 'Mes notes'})
