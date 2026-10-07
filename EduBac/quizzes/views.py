from datetime import timedelta

from django.shortcuts import render, get_object_or_404, redirect
from accounts.decorators import login_required_simple
from django.contrib import messages
from django.utils import timezone
from django.db.models import Avg, Count, Q

from accounts.decorators import teacher_required, student_required
from accounts.models import User
from education.models import Lesson, Course
from classrooms.models import Classroom, ClassroomMember
from .models import Quiz, Question, Choice, QuizAssignment, Attempt, StudentAnswer
from .math_text import normalize_math_text


def _sync_excel_after_submit(attempt):
    """Synchronise le résultat vers les fichiers Excel des classes de l'élève.
    Ne doit jamais faire échouer la soumission du quiz.
    """
    try:
        from classrooms.services.excel_results import sync_attempt_to_class_excel
        sync_attempt_to_class_excel(attempt)
    except Exception:
        import logging
        logging.getLogger(__name__).exception(
            "Échec sync Excel pour attempt=%s (résultat Django conservé)", attempt.pk
        )


def _student_can_access_quiz(user, quiz):
    """
    Contrôle serveur : l'élève ne peut accéder qu'aux quiz qui lui ont été
    explicitement assignés (via sa classe ou une affectation directe).
    """
    if not user.is_authenticated or getattr(user, 'role', None) != 'student':
        return False
    if quiz.status != 'published':
        return False
    return QuizAssignment.objects.filter(quiz=quiz, student=user).exists()


def _notify_assignments(quiz, students, deadline=None):
    """Crée les affectations + notifications uniquement pour la liste donnée."""
    from notifications.services import notify_quiz_assigned
    created = 0
    for st in students:
        obj, was = QuizAssignment.objects.get_or_create(
            quiz=quiz,
            student=st,
            defaults={'deadline': deadline},
        )
        if was:
            created += 1
            try:
                notify_quiz_assigned(obj)
            except Exception:
                pass
        elif deadline and not obj.deadline:
            obj.deadline = deadline
            obj.save(update_fields=['deadline'])
    return created


# ─── Élève ───────────────────────────────────────────────────────────────────

@student_required
def quiz_detail(request, pk):
    quiz = get_object_or_404(Quiz, pk=pk, status='published')
    if not _student_can_access_quiz(request.user, quiz):
        messages.error(request, "Ce quiz ne vous est pas destiné.")
        return redirect('quizzes:assigned')
    return render(request, 'quizzes/detail.html', {
        'quiz': quiz,
        'page_title': quiz.title,
    })


@student_required
def start_quiz(request, pk):
    quiz = get_object_or_404(Quiz, pk=pk, status='published')
    if not _student_can_access_quiz(request.user, quiz):
        messages.error(request, "Ce quiz ne vous est pas destiné.")
        return redirect('quizzes:assigned')
    # Un élève ne peut pas repasser un quiz déjà terminé
    previous = (
        Attempt.objects
        .filter(student=request.user, quiz=quiz, submitted_at__isnull=False)
        .order_by('-submitted_at')
        .first()
    )
    if previous:
        messages.info(
            request,
            'Tu as déjà terminé ce quiz. Consultation des résultats uniquement.'
        )
        return redirect('quizzes:results', attempt_id=previous.pk)
    # Reprendre une tentative en cours si elle existe
    in_progress = (
        Attempt.objects
        .filter(student=request.user, quiz=quiz, submitted_at__isnull=True)
        .order_by('-started_at')
        .first()
    )
    if in_progress:
        return redirect('quizzes:take', attempt_id=in_progress.pk)
    attempt = Attempt.objects.create(student=request.user, quiz=quiz)
    return redirect('quizzes:take', attempt_id=attempt.pk)


@student_required
def take_quiz(request, attempt_id):
    attempt = get_object_or_404(Attempt, pk=attempt_id, student=request.user)
    if not _student_can_access_quiz(request.user, attempt.quiz):
        messages.error(request, "Ce quiz ne vous est pas destiné.")
        return redirect('quizzes:assigned')
    if attempt.submitted_at:
        return redirect('quizzes:results', attempt_id=attempt.pk)

    questions = list(attempt.quiz.get_questions())
    answered_ids = set(attempt.answers.values_list('question_id', flat=True))
    current = next((q for q in questions if q.id not in answered_ids), None)

    if current is None:
        attempt.submitted_at = timezone.now()
        attempt.save(update_fields=['submitted_at'])
        attempt.calculate_score()
        _sync_excel_after_submit(attempt)
        return redirect('quizzes:results', attempt_id=attempt.pk)

    # Chronomètre PAR QUESTION (défaut 20 s)
    per_q = attempt.quiz.seconds_per_question or 20
    # Clé session pour le début de la question courante
    sess_key = f'qstart_{attempt.pk}_{current.pk}'
    if sess_key not in request.session:
        request.session[sess_key] = timezone.now().isoformat()
        request.session.modified = True
    from datetime import datetime
    try:
        q_start = datetime.fromisoformat(request.session[sess_key])
        if timezone.is_naive(q_start):
            q_start = timezone.make_aware(q_start)
    except Exception:
        q_start = timezone.now()
        request.session[sess_key] = q_start.isoformat()
    deadline_q = q_start + timedelta(seconds=per_q)
    remaining = max(0, int((deadline_q - timezone.now()).total_seconds()))

    if request.method == 'POST':
        answer_text = request.POST.get('answer', '').strip()
        timed_out = answer_text == '__timeout__' or timezone.now() >= deadline_q
        if timed_out and not answer_text:
            answer_text = '__timeout__'
        if answer_text == '__timeout__':
            # Question sans réponse → incorrecte, passer à la suivante
            StudentAnswer.objects.get_or_create(
                attempt=attempt,
                question=current,
                defaults={
                    'answer': '',
                    'is_correct': False,
                    'explanation': current.explanation,
                },
            )
            request.session.pop(sess_key, None)
            # Si c'était la dernière question
            if len(answered_ids) + 1 >= len(questions):
                attempt.submitted_at = timezone.now()
                attempt.save(update_fields=['submitted_at'])
                attempt.calculate_score()
                _sync_excel_after_submit(attempt)
                messages.warning(request, 'Temps écoulé sur une ou plusieurs questions.')
                return redirect('quizzes:results', attempt_id=attempt.pk)
            return redirect('quizzes:take', attempt_id=attempt.pk)
        if answer_text:
            # Vérification côté serveur uniquement — aucune solution renvoyée au navigateur
            is_correct = current.check_answer(answer_text)
            StudentAnswer.objects.get_or_create(
                attempt=attempt,
                question=current,
                defaults={
                    'answer': answer_text,
                    'is_correct': is_correct,
                    'explanation': current.explanation,
                },
            )
            request.session.pop(sess_key, None)
            # Pas de feedback / solution pendant le quiz → question suivante ou résultats
            if len(answered_ids) + 1 >= len(questions):
                attempt.submitted_at = timezone.now()
                attempt.save(update_fields=['submitted_at'])
                attempt.calculate_score()
                _sync_excel_after_submit(attempt)
                try:
                    from notifications.services import notify_quiz_result
                    notify_quiz_result(attempt)
                except Exception:
                    pass
                return redirect('quizzes:results', attempt_id=attempt.pk)
            return redirect('quizzes:take', attempt_id=attempt.pk)

    progress = len(answered_ids)
    total = len(questions)
    # Ne jamais exposer is_correct / correct_answer au template pendant le quiz
    safe_choices = list(current.get_choices().values('id', 'text', 'order'))
    return render(request, 'quizzes/take.html', {
        'attempt': attempt,
        'question': current,
        'choices': safe_choices,
        'progress': progress + 1,
        'total': total,
        'remaining_seconds': remaining,
        'seconds_per_question': per_q,
        'hint': getattr(current, 'hint', '') or '',
        'page_title': f'Quiz — {attempt.quiz.title}',
    })



@student_required
def question_feedback(request, attempt_id, question_id):
    """
    Correction d'une question : accessible UNIQUEMENT après soumission complète du quiz.
    Pendant le quiz, redirection vers take (aucune solution exposée).
    """
    attempt = get_object_or_404(Attempt, pk=attempt_id, student=request.user)
    if not attempt.submitted_at:
        return redirect('quizzes:take', attempt_id=attempt.pk)
    if not _student_can_access_quiz(request.user, attempt.quiz):
        messages.error(request, "Ce quiz ne vous est pas destiné.")
        return redirect('quizzes:assigned')
    question = get_object_or_404(Question, pk=question_id, quiz=attempt.quiz)
    ans = StudentAnswer.objects.filter(attempt=attempt, question=question).first()
    if not ans:
        return redirect('quizzes:results', attempt_id=attempt.pk)

    questions = list(attempt.quiz.get_questions())
    answered_ids = set(
        attempt.answers.values_list('question_id', flat=True)
    )
    remaining = [q for q in questions if q.pk not in answered_ids]
    is_last = len(remaining) == 0

    if request.method == 'POST':
        if is_last:
            if not attempt.submitted_at:
                attempt.submitted_at = timezone.now()
                attempt.calculate_score()
                _sync_excel_after_submit(attempt)
            return redirect('quizzes:results', attempt_id=attempt.pk)
        return redirect('quizzes:take', attempt_id=attempt.pk)

    return render(request, 'quizzes/feedback.html', {
        'attempt': attempt,
        'question': question,
        'answer': ans,
        'is_last': is_last,
        'page_title': 'Correction',
    })


@student_required
def quiz_results(request, attempt_id):
    """
    Résultats + correction détaillée — uniquement après soumission complète.
    Pendant le quiz, aucune solution n'est exposée.
    """
    attempt = get_object_or_404(Attempt, pk=attempt_id, student=request.user)
    if attempt.student_id != request.user.id:
        messages.error(request, "Accès non autorisé.")
        return redirect('quizzes:assigned')
    if not attempt.submitted_at:
        return redirect('quizzes:take', attempt_id=attempt.pk)
    answers = (
        attempt.get_answers()
        .select_related('question')
        .prefetch_related('question__choices')
        .order_by('question__order')
    )
    correct = answers.filter(is_correct=True).count()
    total = answers.count()
    new_badges = []
    try:
        from accounts.engagement import check_badges_after_quiz
        new_badges = check_badges_after_quiz(request.user, attempt.score) or []
    except Exception:
        new_badges = []

    # Enrichir chaque réponse avec la bonne réponse (côté serveur, après fin du quiz)
    detailed = []
    for a in answers:
        q = a.question
        try:
            correct_choice = next((c for c in q.choices.all() if c.is_correct), None)
        except Exception:
            correct_choice = None
        good_answer = (
            correct_choice.text if correct_choice
            else (q.correct_answer or '')
        )
        try:
            choices_list = list(q.choices.all())
        except Exception:
            choices_list = []
        detailed.append({
            'answer': a,
            'question': q,
            'student_answer': a.answer,
            'is_correct': a.is_correct,
            'good_answer': good_answer,
            'explanation': (q.explanation or a.explanation or ''),
            'choices': choices_list,
        })

    return render(request, 'quizzes/results.html', {
        'attempt': attempt,
        'new_badges': new_badges,
        'answers': answers,
        'detailed': detailed,
        'correct': correct,
        'total': total,
        'wrong': total - correct,
        'page_title': 'Résultats',
    })


@student_required
def assigned_quizzes(request):
    """
    Quiz Assignments — quiz envoyés aux classes de l'élève
    (et assignations directes).
    """
    from classrooms.models import ClassroomMember
    from django.utils import timezone

    memberships = ClassroomMember.objects.filter(user=request.user).select_related('classroom')
    has_class = memberships.exists()
    my_classes = [m.classroom for m in memberships]

    assignments = (
        QuizAssignment.objects
        .filter(student=request.user)
        .select_related(
            'quiz', 'quiz__lesson', 'quiz__lesson__course', 'quiz__created_by'
        )
        .order_by('-assigned_at')
    )

    # Marquer comme "vus" les quiz assignments (pour badge sidebar)
    request.session['quiz_assignments_seen_at'] = timezone.now().isoformat()

    items = []
    for a in assignments:
        last = Attempt.objects.filter(
            student=request.user, quiz=a.quiz, submitted_at__isnull=False
        ).order_by('-submitted_at').first()
        if last:
            status = 'Terminé'
            status_class = 'success'
        elif a.deadline and a.deadline < timezone.now():
            status = 'Expiré'
            status_class = 'secondary'
        elif a.is_active():
            status = 'À faire'
            status_class = 'warning'
        else:
            status = 'Indisponible'
            status_class = 'secondary'
        items.append({
            'assignment': a,
            'quiz': a.quiz,
            'active': a.is_active() and not last,
            'last_attempt': last,
            'status': status,
            'status_class': status_class,
            'teacher': a.quiz.created_by,
            'course': a.quiz.lesson.course if a.quiz.lesson_id else None,
            'lesson': a.quiz.lesson,
        })

    return render(request, 'quizzes/assigned.html', {
        'items': items,
        'has_class': has_class,
        'my_classes': my_classes,
        'page_title': 'Quiz Assignments',
    })


@student_required
def my_results(request):
    """Historique des résultats de l'élève."""
    attempts = (
        Attempt.objects
        .filter(student=request.user, submitted_at__isnull=False)
        .select_related('quiz', 'quiz__lesson')
        .order_by('-submitted_at')
    )
    return render(request, 'quizzes/my_results.html', {
        'attempts': attempts,
        'page_title': 'Mes résultats',
    })


@student_required
def training(request):
    """Entraînement libre : quiz publiés liés au niveau de l'élève."""
    profile = getattr(request.user, 'student_profile', None)
    quizzes = Quiz.objects.filter(status='published').select_related('lesson', 'lesson__course')
    if profile:
        quizzes = quizzes.filter(lesson__course__niveau=profile.niveau)
    quizzes = quizzes.order_by('-created_at')
    return render(request, 'quizzes/training.html', {
        'quizzes': quizzes,
        'page_title': 'Entraînement',
    })


# ─── Enseignant ──────────────────────────────────────────────────────────────

def _publish_scheduled_quizzes():
    """Passe en publié les quiz dont publish_at est atteint."""
    now = timezone.now()
    Quiz.objects.filter(
        status='draft', publish_at__isnull=False, publish_at__lte=now
    ).update(status='published')


@teacher_required
def manage_quizzes(request):
    """Liste des quiz créés / liés à l'enseignant."""
    from education.curriculum import CURRICULUM

    _publish_scheduled_quizzes()
    quizzes = (
        Quiz.objects
        .filter(Q(created_by=request.user) | Q(created_by__isnull=True))
        .select_related('lesson', 'lesson__course')
        .annotate(nb_questions=Count('questions'), nb_attempts=Count('attempts'))
        .order_by('-created_at')
    )
    niveaux = CURRICULUM
    niveau_codes = {niveau['code'] for niveau in niveaux}
    selected_niveau = (request.GET.get('niveau') or '').strip()
    if selected_niveau not in niveau_codes:
        selected_niveau = ''

    all_lessons = Lesson.objects.select_related('course').order_by(
        'course__order', 'course__name', 'order', 'title'
    )
    selected_lesson_id = (request.GET.get('lesson') or '').strip()
    selected_lesson = None
    if selected_lesson_id.isdecimal():
        requested_lesson = all_lessons.filter(pk=selected_lesson_id).first()
        if requested_lesson and not selected_niveau:
            selected_niveau = requested_lesson.course.niveau
        if (
            requested_lesson
            and selected_niveau in niveau_codes
            and requested_lesson.course.niveau == selected_niveau
        ):
            selected_lesson = requested_lesson
        else:
            selected_lesson_id = ''
    else:
        selected_lesson_id = ''

    lessons = (
        all_lessons.filter(course__niveau=selected_niveau)
        if selected_niveau
        else Lesson.objects.none()
    )
    if selected_lesson:
        quizzes = quizzes.filter(lesson=selected_lesson)
    elif selected_niveau:
        quizzes = quizzes.filter(lesson__course__niveau=selected_niveau)

    return render(request, 'quizzes/manage.html', {
        'quizzes': quizzes,
        'niveaux': niveaux,
        'selected_niveau': selected_niveau,
        'lessons': lessons,
        'all_lessons': all_lessons,
        'selected_lesson': selected_lesson,
        'selected_lesson_id': selected_lesson_id,
        'page_title': 'Mes quiz',
    })


@teacher_required
def create_quiz(request):
    """Création manuelle désactivée — uniquement via l'IA."""
    messages.info(request, "La création de quiz se fait uniquement avec l'IA.")
    return redirect('quizzes:teacher_ai')


@teacher_required
def assign_quiz(request, pk=None):
    """Affecter un quiz à des élèves ou une classe."""
    quizzes = Quiz.objects.filter(
        Q(created_by=request.user) | Q(status='published')
    ).order_by('-created_at')
    classrooms = Classroom.objects.filter(teacher=request.user)
    students = User.objects.filter(role='student').order_by('username')

    selected_quiz = get_object_or_404(Quiz, pk=pk) if pk else None

    if request.method == 'POST':
        quiz_id = request.POST.get('quiz') or (pk and str(pk))
        quiz = get_object_or_404(Quiz, pk=quiz_id)
        target = request.POST.get('target', 'students')  # students | classroom
        deadline_raw = request.POST.get('deadline') or None
        deadline = None
        if deadline_raw:
            try:
                deadline = timezone.datetime.fromisoformat(deadline_raw)
                if timezone.is_naive(deadline):
                    deadline = timezone.make_aware(deadline)
            except ValueError:
                deadline = None

        created = 0
        if target == 'classroom':
            class_id = request.POST.get('classroom')
            if not class_id:
                messages.error(request, "Sélectionnez une classe destinataire.")
                return redirect('quizzes:assign')
            classroom = get_object_or_404(
                Classroom, pk=class_id, teacher=request.user, is_active=True
            )
            quiz.status = 'published'
            quiz.classroom = classroom
            quiz.save(update_fields=['status', 'classroom'])
            student_list = [m.user for m in classroom.members.select_related('user')]
            created = _notify_assignments(quiz, student_list, deadline=deadline)
            messages.success(
                request,
                f'Quiz assigné à la classe {classroom.name} ({created} élève(s)).'
            )
            return redirect('quizzes:manage')
        else:
            # Affectation individuelle (liste d'élèves)
            student_ids = request.POST.getlist('students')
            student_list = list(
                User.objects.filter(pk__in=student_ids, role='student')
            )
            if student_list:
                quiz.status = 'published'
                quiz.save(update_fields=['status'])
                created = _notify_assignments(quiz, student_list, deadline=deadline)
            messages.success(request, f'Quiz assigné à {created} élève(s).')
            return redirect('quizzes:manage')

    return render(request, 'quizzes/assign.html', {
        'quizzes': quizzes,
        'classrooms': classrooms,
        'students': students,
        'selected_quiz': selected_quiz,
        'page_title': 'Affecter un quiz',
    })


@teacher_required
def student_results(request):
    """
    Résultats des élèves par classe :
    élève, quiz, score, date/heure — filtre par classe + export Excel.
    """
    from classrooms.models import Classroom, ClassroomMember

    classrooms = Classroom.objects.filter(teacher=request.user).order_by('name')
    class_id = request.GET.get('classe') or ''
    quiz_id = request.GET.get('quiz') or ''

    attempts = (
        Attempt.objects
        .filter(submitted_at__isnull=False)
        .select_related('student', 'quiz', 'quiz__lesson', 'quiz__created_by')
        .order_by('-submitted_at')
    )
    if not request.user.is_superuser:
        attempts = attempts.filter(
            Q(quiz__created_by=request.user) |
            Q(student__classroom_memberships__classroom__teacher=request.user)
        ).distinct()

    selected_class = None
    if class_id:
        selected_class = get_object_or_404(Classroom, pk=class_id, teacher=request.user)
        student_ids = ClassroomMember.objects.filter(
            classroom=selected_class
        ).values_list('user_id', flat=True)
        attempts = attempts.filter(student_id__in=student_ids)

    if quiz_id:
        attempts = attempts.filter(quiz_id=quiz_id)

    # Quiz list for filter (those of teacher or seen in attempts)
    quizzes = Quiz.objects.filter(created_by=request.user).order_by('-created_at')[:50]

    stats = attempts.aggregate(
        avg=Avg('score'),
        total=Count('id'),
    )
    return render(request, 'quizzes/student_results.html', {
        'attempts': attempts[:300],
        'stats': stats,
        'classrooms': classrooms,
        'selected_class': selected_class,
        'class_id': class_id,
        'quiz_id': quiz_id,
        'quizzes': quizzes,
        'page_title': 'Résultats des élèves',
    })


@teacher_required
def publish_quiz(request, pk):
    quiz = get_object_or_404(Quiz, pk=pk)
    if quiz.created_by_id and quiz.created_by_id != request.user.id and not request.user.is_superuser:
        messages.error(request, 'Vous ne pouvez pas modifier ce quiz.')
        return redirect('quizzes:manage')
    quiz.status = 'published'
    quiz.question_count = quiz.questions.count()
    quiz.save(update_fields=['status', 'question_count'])
    messages.success(request, f'Quiz « {quiz.title} » publié.')
    return redirect('quizzes:manage')


@teacher_required
def teacher_ai_quiz(request):
    """
    Page unique enseignant :
    niveau → leçon → nb questions → secondes/question → Generate (IA) → Envoyer au niveau.
    """
    from education.curriculum import CURRICULUM
    from education.models import Lesson, Course
    from accounts.models import User, StudentProfile
    from ai.services import AIService

    niveaux = CURRICULUM
    selected_niveau = request.GET.get('niveau') or request.POST.get('niveau') or ''
    selected_lesson_id = (
        request.POST.get('lesson', '')
        if request.method == 'POST'
        else request.GET.get('lesson', '')
    )
    selected_lesson_id = str(selected_lesson_id).strip()
    selected_lesson = None
    if selected_lesson_id.isdecimal():
        selected_lesson = (
            Lesson.objects.select_related('course')
            .filter(pk=selected_lesson_id)
            .first()
        )
        if selected_lesson and not selected_niveau:
            selected_niveau = selected_lesson.course.niveau

    all_lessons = Lesson.objects.select_related('course').order_by(
        'course__order', 'order', 'title'
    )
    lessons = Lesson.objects.none()
    if selected_niveau:
        lessons = Lesson.objects.filter(course__niveau=selected_niveau).order_by('order')
    if selected_lesson_id and not lessons.filter(pk=selected_lesson_id).exists():
        selected_lesson_id = ''

    preview = None
    quiz_created = None
    error = None
    quiz_description = ''

    if request.method == 'POST':
        action = request.POST.get('action', 'generate')
        niveau = request.POST.get('niveau', '').strip()
        lesson_id = request.POST.get('lesson')
        quiz_description = (request.POST.get('description') or '').strip()
        n_questions = int(request.POST.get('question_count') or 5)
        sec = int(request.POST.get('seconds_per_question') or 20)
        difficulty = request.POST.get('difficulty', 'moyen')
        n_questions = max(1, min(n_questions, 20))
        sec = max(5, min(sec, 120))

        selected_niveau = niveau
        lessons = Lesson.objects.filter(course__niveau=niveau).order_by('order') if niveau else Lesson.objects.none()
        if selected_lesson_id and not lessons.filter(pk=selected_lesson_id).exists():
            selected_lesson_id = ''

        if not lesson_id:
            error = 'Veuillez choisir une leçon.'
        else:
            lesson = get_object_or_404(Lesson, pk=lesson_id)

            if action == 'generate':
                try:
                    from ai.providers import AIProviderError
                    provider = (request.POST.get('ai_provider') or '').strip() or None
                    model = (request.POST.get('ai_model') or '').strip() or None
                    ai = AIService(provider=provider, model=model)
                    data = ai.generate_quiz_from_lesson(
                        lesson, n_questions, difficulty,
                        provider=provider, model=model,
                        description=quiz_description,
                    )
                    # Créer le quiz + questions
                    quiz = Quiz.objects.create(
                        title=data.get('title') or f'Quiz — {lesson.title}',
                        description=quiz_description,
                        lesson=lesson,
                        duration=max(1, (n_questions * sec) // 60 + 1),
                        seconds_per_question=sec,
                        question_count=n_questions,
                        difficulty=difficulty,
                        status='draft',
                        created_by=request.user,
                    )
                    for i, qdata in enumerate(data.get('questions', []), start=1):
                        correct_text = normalize_math_text(
                            qdata.get('correct_answer', '')
                        )
                        q = Question.objects.create(
                            quiz=quiz,
                            text=normalize_math_text(qdata.get('text', '')),
                            correct_answer=correct_text,
                            explanation=normalize_math_text(qdata.get('explanation', '')),
                            hint=normalize_math_text(qdata.get('hint', '')),
                            order=i,
                        )
                        for j, c in enumerate(qdata.get('choices', [])):
                            if isinstance(c, dict):
                                ctext = normalize_math_text(c.get('text', ''))
                                is_ok = c.get(
                                    'is_correct',
                                    ctext.strip().lower() == correct_text.strip().lower(),
                                )
                            else:
                                ctext = normalize_math_text(c)
                                is_ok = (
                                    ctext.strip().lower()
                                    == correct_text.strip().lower()
                                )
                            Choice.objects.create(
                                question=q,
                                text=ctext,
                                is_correct=is_ok,
                                order=j,
                            )
                    quiz.question_count = quiz.questions.count()
                    quiz.save(update_fields=['question_count'])
                    quiz_created = quiz
                    preview = quiz.get_questions().prefetch_related('choices')
                    messages.success(request, f'Quiz généré : {quiz.question_count} question(s). Vérifiez puis envoyez.')
                except Exception as e:
                    error = f'Erreur IA : {e}'

            elif action == 'send':
                quiz_id = request.POST.get('quiz_id')
                quiz = get_object_or_404(Quiz, pk=quiz_id, created_by=request.user)
                classroom_id = (request.POST.get('classroom') or '').strip()
                deadline_raw = request.POST.get('deadline') or None
                deadline = None
                if deadline_raw:
                    try:
                        deadline = timezone.datetime.fromisoformat(deadline_raw)
                        if timezone.is_naive(deadline):
                            deadline = timezone.make_aware(deadline)
                    except ValueError:
                        deadline = None

                # Classe obligatoire : uniquement les classes du professeur connecté
                if not classroom_id:
                    messages.error(
                        request,
                        "Sélectionnez une classe destinataire avant d'envoyer le quiz."
                    )
                    return redirect('quizzes:teacher_ai')
                classroom = get_object_or_404(
                    Classroom, pk=classroom_id, teacher=request.user, is_active=True
                )
                member_ids = list(
                    ClassroomMember.objects.filter(classroom=classroom)
                    .values_list('user_id', flat=True)
                )
                student_list = list(
                    User.objects.filter(id__in=member_ids, role='student')
                )
                if not student_list:
                    messages.warning(
                        request,
                        f"La classe « {classroom.name} » n'a aucun élève. "
                        "Faites rejoindre vos élèves avec le code d'invitation."
                    )
                    return redirect('quizzes:teacher_ai')

                quiz.status = 'published'
                quiz.question_count = quiz.questions.count()
                quiz.classroom = classroom
                quiz.save(update_fields=['status', 'question_count', 'classroom'])

                created = _notify_assignments(quiz, student_list, deadline=deadline)
                messages.success(
                    request,
                    f'Quiz « {quiz.title} » envoyé à la classe {classroom.name} '
                    f'({created} élève(s) notifié(s)).'
                )
                return redirect('quizzes:manage')

    from ai.services import available_providers
    classrooms = Classroom.objects.filter(teacher=request.user, is_active=True)
    return render(request, 'quizzes/teacher_ai_quiz.html', {
        'niveaux': niveaux,
        'selected_niveau': selected_niveau,
        'selected_lesson_id': selected_lesson_id,
        'lessons': lessons,
        'all_lessons': all_lessons,
        'preview': preview,
        'quiz_created': quiz_created,
        'quiz_description': quiz_description,
        'classrooms': classrooms,
        'error': error,
        'ai_providers': available_providers(),
        'page_title': 'Générer un quiz',
    })


@teacher_required
def edit_quiz_questions(request, pk):
    """Édition manuelle des questions avant envoi."""
    quiz = get_object_or_404(Quiz, pk=pk)
    if quiz.created_by_id and quiz.created_by_id != request.user.id and not request.user.is_superuser:
        messages.error(request, 'Vous ne pouvez pas modifier ce quiz.')
        return redirect('quizzes:manage')
    questions = quiz.get_questions().prefetch_related('choices')

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'save':
            for q in questions:
                text = request.POST.get(f'q_{q.pk}_text', '').strip()
                correct = request.POST.get(f'q_{q.pk}_correct', '').strip()
                expl = request.POST.get(f'q_{q.pk}_expl', '').strip()
                if text:
                    q.text = text
                    q.correct_answer = correct
                    q.explanation = expl
                    q.save()
                for c in q.choices.all():
                    ctext = request.POST.get(f'c_{c.pk}_text', '').strip()
                    if ctext:
                        c.text = ctext
                        c.is_correct = (ctext == correct) or (request.POST.get(f'c_{c.pk}_ok') == 'on')
                        c.save()
            messages.success(request, 'Questions enregistrées.')
            return redirect('quizzes:edit_questions', pk=quiz.pk)
        if action == 'delete_q':
            qid = request.POST.get('question_id')
            Question.objects.filter(pk=qid, quiz=quiz).delete()
            quiz.question_count = quiz.questions.count()
            quiz.save(update_fields=['question_count'])
            messages.info(request, 'Question supprimée.')
            return redirect('quizzes:edit_questions', pk=quiz.pk)

        if action == 'add_q':
            next_order = (quiz.questions.count() or 0) + 1
            q = Question.objects.create(
                quiz=quiz,
                text='Nouvelle question — modifiez l\'énoncé',
                correct_answer='',
                explanation='',
                order=next_order,
            )
            # 4 choix vides par défaut (QCM)
            for i, label in enumerate(['A', 'B', 'C', 'D']):
                Choice.objects.create(
                    question=q,
                    text=f'Choix {label}',
                    is_correct=(i == 0),
                    order=i,
                )
            if not q.correct_answer:
                q.correct_answer = 'Choix A'
                q.save(update_fields=['correct_answer'])
            quiz.question_count = quiz.questions.count()
            quiz.save(update_fields=['question_count'])
            messages.success(request, f'Question {next_order} ajoutée. Complétez l\'énoncé et les choix.')
            return redirect('quizzes:edit_questions', pk=quiz.pk)

        if action == 'add_choice':
            qid = request.POST.get('question_id')
            q = Question.objects.filter(pk=qid, quiz=quiz).first()
            if q:
                n = q.choices.count()
                Choice.objects.create(
                    question=q,
                    text=f'Nouveau choix',
                    is_correct=False,
                    order=n,
                )
                messages.success(request, 'Choix ajouté.')
            return redirect('quizzes:edit_questions', pk=quiz.pk)

    return render(request, 'quizzes/edit_questions.html', {
        'quiz': quiz,
        'questions': questions,
        'page_title': f'Modifier — {quiz.title}',
    })


@student_required
def review_attempt(request, attempt_id):
    """Mode révision : revoir questions + bonnes réponses + explications."""
    attempt = get_object_or_404(Attempt, pk=attempt_id, student=request.user)
    if not attempt.submitted_at:
        return redirect('quizzes:take', attempt_id=attempt.pk)
    answers = attempt.get_answers().select_related('question').prefetch_related('question__choices')
    return render(request, 'quizzes/review.html', {
        'attempt': attempt,
        'answers': answers,
        'page_title': 'Révision',
    })


@teacher_required

@teacher_required
def export_results_excel(request):
    """Export Excel (.xlsx) des résultats — filtrable par classe / quiz."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from django.http import HttpResponse
    from classrooms.models import Classroom, ClassroomMember

    class_id = request.GET.get('classe') or ''
    quiz_id = request.GET.get('quiz') or ''

    attempts = (
        Attempt.objects
        .filter(submitted_at__isnull=False)
        .select_related('student', 'quiz', 'quiz__lesson')
        .order_by('student__last_name', 'student__first_name', '-submitted_at')
    )
    if not request.user.is_superuser:
        attempts = attempts.filter(
            Q(quiz__created_by=request.user) |
            Q(student__classroom_memberships__classroom__teacher=request.user)
        ).distinct()

    class_name = 'toutes_classes'
    if class_id:
        classroom = get_object_or_404(Classroom, pk=class_id, teacher=request.user)
        class_name = classroom.name.replace(' ', '_')[:40]
        student_ids = ClassroomMember.objects.filter(
            classroom=classroom
        ).values_list('user_id', flat=True)
        attempts = attempts.filter(student_id__in=student_ids)

    if quiz_id:
        attempts = attempts.filter(quiz_id=quiz_id)

    wb = Workbook()
    ws = wb.active
    ws.title = 'Resultats'

    headers = [
        'Classe', 'Élève', 'E-mail', 'Quiz', 'Leçon',
        'Score (%)', 'Date', 'Heure',
    ]
    header_fill = PatternFill('solid', fgColor='1A6B6B')
    header_font = Font(color='FFFFFF', bold=True)
    thin = Border(
        left=Side(style='thin', color='CCCCCC'),
        right=Side(style='thin', color='CCCCCC'),
        top=Side(style='thin', color='CCCCCC'),
        bottom=Side(style='thin', color='CCCCCC'),
    )
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal='center')
        cell.border = thin

    # Map student -> class names for teacher
    membership_map = {}
    from classrooms.models import ClassroomMember as CM
    for m in CM.objects.filter(classroom__teacher=request.user).select_related('classroom'):
        membership_map.setdefault(m.user_id, [])
        if m.classroom.name not in membership_map[m.user_id]:
            membership_map[m.user_id].append(m.classroom.name)

    row = 2
    for a in attempts[:5000]:
        if class_id:
            classes = class_name.replace('_', ' ')
        else:
            classes = ', '.join(membership_map.get(a.student_id, []))
        ws.cell(row=row, column=1, value=classes).border = thin
        ws.cell(row=row, column=2, value=a.student.get_full_name() or a.student.username).border = thin
        ws.cell(row=row, column=3, value=a.student.email or '').border = thin
        ws.cell(row=row, column=4, value=a.quiz.title).border = thin
        ws.cell(row=row, column=5, value=a.quiz.lesson.title if a.quiz.lesson_id else '').border = thin
        cell_score = ws.cell(row=row, column=6, value=float(a.score or 0))
        cell_score.border = thin
        cell_score.alignment = Alignment(horizontal='center')
        ws.cell(
            row=row, column=7,
            value=a.submitted_at.strftime('%d/%m/%Y') if a.submitted_at else ''
        ).border = thin
        ws.cell(
            row=row, column=8,
            value=a.submitted_at.strftime('%H:%M') if a.submitted_at else ''
        ).border = thin
        row += 1

    for col in range(1, 9):
        ws.column_dimensions[chr(64 + col)].width = 18
    ws.column_dimensions['B'].width = 24
    ws.column_dimensions['D'].width = 28
    ws.column_dimensions['E'].width = 28

    filename = f'edubac_resultats_{class_name}.xlsx'
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    wb.save(response)
    return response


@teacher_required
def export_results_csv(request):
    """Export CSV des résultats élèves."""
    import csv
    from django.http import HttpResponse
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="edubac_resultats.csv"'
    response.write('\ufeff')  # BOM UTF-8
    writer = csv.writer(response, delimiter=';')
    writer.writerow(['Élève', 'Username', 'Quiz', 'Score', 'Date'])
    attempts = (
        Attempt.objects
        .filter(submitted_at__isnull=False)
        .select_related('student', 'quiz')
        .order_by('-submitted_at')
    )
    if not request.user.is_superuser:
        attempts = attempts.filter(
            Q(quiz__created_by=request.user) |
            Q(student__classroom_memberships__classroom__teacher=request.user)
        ).distinct()
    for a in attempts[:2000]:
        writer.writerow([
            a.student.get_full_name(),
            a.student.username,
            a.quiz.title,
            a.score,
            a.submitted_at.strftime('%d/%m/%Y %H:%M') if a.submitted_at else '',
        ])
    return response


@student_required
def retake_quiz(request, pk):
    """Interdit : un quiz terminé ne peut pas être repassé."""
    quiz = get_object_or_404(Quiz, pk=pk)
    previous = (
        Attempt.objects
        .filter(student=request.user, quiz=quiz, submitted_at__isnull=False)
        .order_by('-submitted_at')
        .first()
    )
    if previous:
        messages.warning(
            request,
            'Tu as déjà passé ce quiz. Tu ne peux pas le recommencer.'
        )
        return redirect('quizzes:results', attempt_id=previous.pk)
    # Pas encore terminé → rediriger vers start (qui gère tentative en cours)
    return redirect('quizzes:start', pk=pk)


@teacher_required
def question_stats(request, pk):
    """Taux de réussite par question pour un quiz."""
    quiz = get_object_or_404(Quiz, pk=pk)
    if quiz.created_by_id and quiz.created_by_id != request.user.id and not request.user.is_superuser:
        messages.error(request, 'Accès refusé.')
        return redirect('quizzes:manage')
    from django.db.models import Count, Q
    questions = quiz.get_questions()
    rows = []
    for q in questions:
        total = StudentAnswer.objects.filter(question=q).count()
        correct = StudentAnswer.objects.filter(question=q, is_correct=True).count()
        pct = int(100 * correct / total) if total else None
        rows.append({'question': q, 'total': total, 'correct': correct, 'pct': pct})
    return render(request, 'quizzes/question_stats.html', {
        'quiz': quiz,
        'rows': rows,
        'page_title': f'Stats — {quiz.title}',
    })


@teacher_required
def comment_attempt(request, attempt_id):
    attempt = get_object_or_404(Attempt, pk=attempt_id, submitted_at__isnull=False)
    if request.method == 'POST':
        attempt.teacher_comment = (request.POST.get('comment') or '').strip()
        attempt.save(update_fields=['teacher_comment'])
        messages.success(request, 'Commentaire enregistré.')
        return redirect('quizzes:student_results')
    return render(request, 'quizzes/comment_attempt.html', {
        'attempt': attempt,
        'page_title': 'Commentaire',
    })


@teacher_required
def duplicate_quiz(request, pk):
    quiz = get_object_or_404(Quiz, pk=pk)
    if quiz.created_by_id and quiz.created_by_id != request.user.id and not request.user.is_superuser:
        messages.error(request, 'Accès refusé.')
        return redirect('quizzes:manage')
    new_quiz = Quiz.objects.create(
        title=f'{quiz.title} (copie)',
        duration=quiz.duration,
        seconds_per_question=quiz.seconds_per_question,
        question_count=quiz.question_count,
        difficulty=quiz.difficulty,
        description=quiz.description,
        status='draft',
        lesson=quiz.lesson,
        created_by=request.user,
    )
    for q in quiz.get_questions():
        nq = Question.objects.create(
            quiz=new_quiz,
            text=q.text,
            correct_answer=q.correct_answer,
            explanation=q.explanation,
            hint=getattr(q, 'hint', '') or '',
            order=q.order,
        )
        for c in q.choices.all():
            Choice.objects.create(
                question=nq, text=c.text, is_correct=c.is_correct, order=c.order
            )
    messages.success(request, f'Quiz dupliqué : {new_quiz.title}')
    return redirect('quizzes:edit_questions', pk=new_quiz.pk)


@student_required
def error_analysis(request):
    """Questions le plus souvent ratées par l'élève."""
    from django.db.models import Count
    wrong = (
        StudentAnswer.objects
        .filter(attempt__student=request.user, is_correct=False)
        .values('question_id', 'question__text', 'question__quiz__title')
        .annotate(n=Count('id'))
        .order_by('-n')[:20]
    )
    return render(request, 'quizzes/error_analysis.html', {
        'wrong': wrong,
        'page_title': 'Analyse des erreurs',
    })


@student_required
def class_ranking(request):
    """Classement simple par score moyen (classe de l'élève si membre)."""
    from django.db.models import Avg, Count
    from classrooms.models import ClassroomMember
    membership = ClassroomMember.objects.filter(user=request.user).select_related('classroom').first()
    rows = []
    classroom = None
    if membership:
        classroom = membership.classroom
        student_ids = ClassroomMember.objects.filter(classroom=classroom).values_list('user_id', flat=True)
        rows = list(
            Attempt.objects.filter(
                student_id__in=student_ids, submitted_at__isnull=False
            )
            .values('student_id', 'student__first_name', 'student__last_name')
            .annotate(avg=Avg('score'), n=Count('id'))  # Count from django.db.models
            .order_by('-avg')[:30]
        )
    return render(request, 'quizzes/ranking.html', {
        'rows': rows,
        'classroom': classroom,
        'page_title': 'Classement',
    })


@teacher_required
def teacher_stats(request):
    """Tableau de bord statistiques enseignant."""
    from django.db.models import Avg, Count, Q
    from classrooms.models import Classroom, ClassroomMember

    user = request.edubac_user
    quizzes = Quiz.objects.filter(created_by=user).select_related('lesson')
    quiz_ids = list(quizzes.values_list('pk', flat=True))

    attempts = Attempt.objects.filter(
        quiz_id__in=quiz_ids, submitted_at__isnull=False
    ).select_related('student', 'quiz')

    total_attempts = attempts.count()
    avg_score = attempts.aggregate(a=Avg('score'))['a'] or 0

    # Par quiz
    by_quiz = []
    for q in quizzes.order_by('-created_at')[:15]:
        qs = attempts.filter(quiz=q)
        n = qs.count()
        by_quiz.append({
            'quiz': q,
            'n': n,
            'avg': qs.aggregate(a=Avg('score'))['a'] or 0,
            'pass_rate': qs.filter(score__gte=50).count() * 100 / n if n else 0,
        })

    # Élèves les plus actifs
    active_students = (
        attempts.values('student_id', 'student__first_name', 'student__last_name', 'student__username')
        .annotate(n=Count('id'), avg=Avg('score'))
        .order_by('-n')[:12]
    )

    # Questions les plus ratées
    hard_questions = (
        StudentAnswer.objects
        .filter(attempt__quiz_id__in=quiz_ids, is_correct=False)
        .values('question_id', 'question__text', 'question__quiz__title')
        .annotate(fails=Count('id'))
        .order_by('-fails')[:10]
    )

    classrooms = Classroom.objects.filter(teacher=user)
    class_stats = []
    for c in classrooms:
        member_ids = list(c.members.values_list('user_id', flat=True))
        ca = attempts.filter(student_id__in=member_ids)
        n = ca.count()
        class_stats.append({
            'classroom': c,
            'members': len(member_ids),
            'attempts': n,
            'avg': ca.aggregate(a=Avg('score'))['a'] or 0,
        })

    return render(request, 'quizzes/teacher_stats.html', {
        'total_attempts': total_attempts,
        'avg_score': round(avg_score, 1),
        'quiz_count': quizzes.count(),
        'by_quiz': by_quiz,
        'active_students': active_students,
        'hard_questions': hard_questions,
        'class_stats': class_stats,
        'page_title': 'Statistiques',
    })


@teacher_required
def schedule_quiz(request, pk):
    """Programmer la publication d'un quiz."""
    quiz = get_object_or_404(Quiz, pk=pk)
    if quiz.created_by_id and quiz.created_by_id != request.user.id and not request.user.is_superuser:
        messages.error(request, 'Accès refusé.')
        return redirect('quizzes:manage')
    if request.method == 'POST':
        raw = (request.POST.get('publish_at') or '').strip()
        if raw:
            from django.utils.dateparse import parse_datetime
            dt = parse_datetime(raw)
            if dt is None:
                # datetime-local: 2026-10-01T14:30
                try:
                    from datetime import datetime
                    dt = datetime.strptime(raw, '%Y-%m-%dT%H:%M')
                    if timezone.is_naive(dt):
                        dt = timezone.make_aware(dt)
                except ValueError:
                    dt = None
            if dt:
                quiz.publish_at = dt
                if quiz.status == 'published':
                    quiz.status = 'draft'
                quiz.save(update_fields=['publish_at', 'status'])
                messages.success(request, f'Publication programmée pour {dt.strftime("%d/%m/%Y %H:%M")}.')
            else:
                messages.error(request, 'Date invalide.')
        else:
            quiz.publish_at = None
            quiz.save(update_fields=['publish_at'])
            messages.info(request, 'Programmation annulée.')
        return redirect('quizzes:manage')
    return render(request, 'quizzes/schedule_quiz.html', {
        'quiz': quiz,
        'page_title': 'Programmer le quiz',
    })
