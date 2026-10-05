from django.shortcuts import render, get_object_or_404, redirect
from accounts.decorators import login_required_simple
from django.contrib import messages
from education.models import Lesson, Course
from quizzes.models import Quiz, Question, Choice
from quizzes.views import _plain_math_text
from .services import AIService
from .models import AIConversation, AIMessage


def _handle_assistant_post(request, lesson, question, level, style, previous, conv_id=None):
    service = AIService()
    response_text = service.generate_explanation(
        lesson,
        question,
        level=level or 'normal',
        style=style or 'standard',
        previous_answer=previous or '',
    )
    if conv_id:
        conversation = get_object_or_404(AIConversation, pk=conv_id, user=request.user)
    else:
        conversation = AIConversation.objects.create(
            user=request.user,
            lesson=lesson,
            title=question[:80],
        )
    label = {
        'autrement': '[Autrement] ',
        'etapes': '[Étapes] ',
        'exemple': '[Exemple] ',
        'erreur': '[Erreur] ',
    }.get(style, '')
    AIMessage.objects.create(
        conversation=conversation,
        role='user',
        content=f"{label}{question}" if style != 'autrement' else f"{label}Explique autrement",
    )
    AIMessage.objects.create(
        conversation=conversation, role='assistant', content=response_text or ''
    )
    return conversation, response_text


@login_required_simple
def assistant(request):
    courses = Course.objects.all().order_by('niveau', 'order')
    response_text = None
    conversation = None
    history = AIConversation.objects.filter(user=request.user)[:10]
    level = request.POST.get('level') or request.GET.get('level') or 'normal'
    style = 'standard'

    if request.method == 'POST':
        lesson_id = request.POST.get('lesson_id')
        question = request.POST.get('question', '').strip()
        conv_id = request.POST.get('conversation_id')
        level = request.POST.get('level', 'normal')
        style = request.POST.get('style', 'standard')
        previous = request.POST.get('previous_answer', '')
        # Boutons spéciaux
        if style == 'autrement' and not question:
            question = "Peux-tu m'expliquer cela autrement, plus simplement ?"
        if lesson_id and question:
            lesson = get_object_or_404(Lesson, pk=lesson_id)
            try:
                conversation, response_text = _handle_assistant_post(
                    request, lesson, question, level, style, previous, conv_id
                )
            except Exception as e:
                messages.error(request, f'Erreur IA : {e}')
    elif request.GET.get('c'):
        conversation = get_object_or_404(
            AIConversation, pk=request.GET.get('c'), user=request.user
        )

    return render(request, 'ai/assistant.html', {
        'courses': courses,
        'response': response_text,
        'conversation': conversation,
        'history': history,
        'level': level,
        'page_title': 'Assistant IA',
    })


@login_required_simple
def assistant_lesson(request, lesson_id):
    lesson = get_object_or_404(Lesson, pk=lesson_id)
    response_text = None
    conversation = None
    level = request.POST.get('level', 'normal')
    if request.method == 'POST':
        question = request.POST.get('question', '').strip()
        style = request.POST.get('style', 'standard')
        previous = request.POST.get('previous_answer', '')
        level = request.POST.get('level', 'normal')
        if style == 'autrement' and not question:
            question = "Peux-tu m'expliquer cela autrement ?"
        if question:
            try:
                conversation, response_text = _handle_assistant_post(
                    request, lesson, question, level, style, previous
                )
            except Exception as e:
                messages.error(request, f'Erreur IA : {e}')
    return render(request, 'ai/assistant_lesson.html', {
        'lesson': lesson,
        'response': response_text,
        'conversation': conversation,
        'level': level,
        'page_title': f'Assistant IA — {lesson.title}',
    })


@login_required_simple
def generate_quiz(request, lesson_id):
    if not (hasattr(request.user, 'role') and request.user.role == 'teacher'):
        messages.error(request, 'Réservé aux enseignants.')
        return redirect('education:home')
    lesson = get_object_or_404(Lesson, pk=lesson_id)
    if request.method == 'POST':
        count = int(request.POST.get('question_count', 5))
        difficulty = request.POST.get('difficulty', 'moyen')
        try:
            service = AIService()
            data = service.generate_quiz_from_lesson(lesson, count, difficulty)
            quiz = Quiz.objects.create(
                title=data.get('title', f'Quiz IA — {lesson.title}'),
                duration=30,
                question_count=len(data['questions']),
                difficulty=difficulty,
                status='draft',
                lesson=lesson,
                created_by=request.user,
            )
            for i, qdata in enumerate(data['questions']):
                q = Question.objects.create(
                    text=_plain_math_text(qdata.get('text', '')),
                    explanation=_plain_math_text(qdata.get('explanation', '')),
                    correct_answer=_plain_math_text(qdata.get('correct_answer', '')),
                    hint=_plain_math_text(qdata.get('hint', '')),
                    quiz=quiz,
                    order=i + 1,
                )
                for j, cdata in enumerate(qdata.get('choices', [])):
                    text = cdata['text'] if isinstance(cdata, dict) else str(cdata)
                    text = _plain_math_text(text)
                    is_ok = cdata.get('is_correct', False) if isinstance(cdata, dict) else False
                    Choice.objects.create(text=text, is_correct=is_ok, question=q, order=j)
            messages.success(request, 'Quiz généré.')
            return redirect('quizzes:edit_questions', pk=quiz.pk)
        except Exception as e:
            messages.error(request, f'Erreur IA : {e}')
    return redirect('quizzes:teacher_ai')
