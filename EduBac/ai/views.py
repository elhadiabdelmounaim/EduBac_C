from django.shortcuts import render, get_object_or_404, redirect
from accounts.decorators import login_required_simple
from django.contrib import messages
from django.db import transaction
from django.http import Http404
from django.urls import reverse
import logging
from education.models import Lesson, Course
from quizzes.models import Quiz, Question, Choice
from quizzes.math_text import normalize_math_text
from .services import AIService, QUIZ_MAX_QUESTIONS, public_quiz_error
from .models import AIConversation, AIMessage
from .providers import AIProviderError

logger = logging.getLogger(__name__)


def _handle_assistant_post(request, lesson, question, level, style, previous, conv_id=None):
    conversation = None
    prior = []
    if conv_id:
        conversation = get_object_or_404(
            AIConversation, pk=conv_id, user=request.user, lesson=lesson,
        )
        prior = list(reversed(list(
            conversation.messages.order_by('-created_at', '-pk').values('role', 'content')[:12]
        )))
    previous = next((m['content'] for m in reversed(prior) if m['role'] == 'assistant'), '')
    service = AIService()
    response_text = service.generate_explanation(
        lesson,
        question,
        level=level or 'normal',
        style=style or 'standard',
        previous_answer=previous or '',
        conversation_history=prior,
    )
    label = {
        'autrement': '[Autrement] ',
        'etapes': '[Étapes] ',
        'exemple': '[Exemple] ',
        'erreur': '[Erreur] ',
        'entrainement': '[Entraînement] ',
    }.get(style, '')
    with transaction.atomic():
        if conversation is None:
            conversation = AIConversation.objects.create(
                user=request.user, lesson=lesson, title=question[:80],
            )
        AIMessage.objects.create(
            conversation=conversation, role='user',
            content=f"{label}{question}",
        )
        AIMessage.objects.create(
            conversation=conversation, role='assistant', content=response_text,
        )
        conversation.save(update_fields=['updated_at'])
    return conversation, response_text


@login_required_simple
def assistant(request):
    courses = Course.objects.all().order_by('niveau', 'order')
    response_text = None
    conversation = None
    history = AIConversation.objects.filter(user=request.user)[:10]
    level = request.POST.get('level') or request.GET.get('level') or 'normal'
    style = 'standard'
    question = ''
    selected_lesson = None
    conv_id = request.POST.get('conversation_id') or request.GET.get('c')
    if conv_id:
        if not conv_id.isdigit():
            raise Http404
        conversation = get_object_or_404(AIConversation, pk=conv_id, user=request.user)
        selected_lesson = conversation.lesson
    lesson_id = request.POST.get('lesson_id') or request.GET.get('lesson')
    if lesson_id:
        if not lesson_id.isdigit():
            raise Http404
        selected_lesson = get_object_or_404(Lesson, pk=lesson_id)
    if conversation and selected_lesson != conversation.lesson:
        raise Http404

    if request.method == 'POST':
        question = request.POST.get('question', '').strip()
        level = request.POST.get('level', 'normal')
        style = request.POST.get('style', 'standard')
        previous = request.POST.get('previous_answer', '')
        # Boutons spéciaux
        if style == 'autrement' and not question:
            question = "Peux-tu m'expliquer cela autrement, plus simplement ?"
        if style not in ('standard', 'etapes', 'exemple', 'erreur', 'autrement', 'entrainement'):
            style = 'standard'
        if level not in ('simple', 'normal', 'approfondi'):
            level = 'normal'
        if not selected_lesson:
            messages.error(request, 'Choisis une leçon pour commencer.')
        elif not question or len(question) > 4000:
            messages.error(request, 'Écris une question de 1 à 4 000 caractères.')
        else:
            try:
                conversation, response_text = _handle_assistant_post(
                    request, selected_lesson, question, level, style, previous, conv_id
                )
                return redirect(f"{reverse('ai:assistant')}?c={conversation.pk}&level={level}")
            except AIProviderError as exc:
                if exc.code == 'missing_api_key':
                    messages.error(request, "Le tuteur IA n'est pas encore configuré. Contacte l'administrateur.")
                else:
                    messages.error(request, "Le tuteur IA est momentanément indisponible. Ta question est conservée ci-dessous ; réessaie.")
            except Exception:
                logger.exception("Tutor request failed")
                messages.error(request, "Impossible de répondre pour le moment. Réessaie.")

    return render(request, 'ai/assistant.html', {
        'courses': courses,
        'response': response_text,
        'conversation': conversation,
        'history': history,
        'level': level,
        'question': question,
        'selected_lesson': selected_lesson,
        'page_title': 'Assistant IA',
    })


@login_required_simple
def assistant_lesson(request, lesson_id):
    # Share the same conversation flow, including saved history and validation.
    get_object_or_404(Lesson, pk=lesson_id)
    if request.method == 'POST':
        request.POST = request.POST.copy()
        request.POST['lesson_id'] = str(lesson_id)
        return assistant(request)
    return redirect(f"{reverse('ai:assistant')}?lesson={lesson_id}")


@login_required_simple
def generate_quiz(request, lesson_id):
    if not (hasattr(request.user, 'role') and request.user.role == 'teacher'):
        messages.error(request, 'Réservé aux enseignants.')
        return redirect('education:home')
    lesson = get_object_or_404(Lesson.objects.select_related('course'), pk=lesson_id)
    if request.method == 'POST':
        count = max(1, min(int(request.POST.get('question_count', 5)), QUIZ_MAX_QUESTIONS))
        difficulty = request.POST.get('difficulty', 'moyen')
        try:
            service = AIService()
            data = service.generate_quiz_from_lesson(lesson, count, difficulty)
            from quizzes.generation import save_generated_quiz
            quiz = save_generated_quiz(data,
                title=data.get('title', f'Quiz IA — {lesson.title}'),
                duration=30,
                question_count=len(data['questions']),
                difficulty=difficulty,
                status='draft',
                lesson=lesson,
                created_by=request.user,
            )
            messages.success(request, 'Quiz generated successfully')
            return redirect('quizzes:edit_questions', pk=quiz.pk)
        except Exception as e:
            logger.warning("generate_quiz API error: %s", e)
            messages.error(request, f'Generation failed: {public_quiz_error(e)}')
    return redirect('quizzes:teacher_ai')
