"""Quiz en direct : lancement (professeur), écran projeté, téléphone de l'élève, échanges JSON."""
import json

from django.contrib import messages
from django.db.models import Count, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.decorators import login_required_simple, student_required, teacher_required

from . import direct
from .models import LiveParticipant, LiveSession, Quiz


def _admin(user):
    return bool(getattr(user, 'is_staff', False) or getattr(user, 'is_superuser', False))


def _session_hote(request, pk):
    session = get_object_or_404(LiveSession.objects.select_related('quiz', 'classroom'), pk=pk)
    if session.host_id != request.user.pk and not _admin(request.user):
        raise Http404
    return session


@teacher_required
def lancer(request, pk):
    """Choisir la classe, puis ouvrir la salle d'attente sur l'écran de la classe."""
    from classrooms.models import Classroom
    quiz = get_object_or_404(Quiz.objects.select_related('lesson__course'), pk=pk)
    if quiz.created_by_id and quiz.created_by_id != request.user.pk and not _admin(request.user):
        raise Http404
    classes = Classroom.objects.filter(is_active=True, niveau=quiz.lesson.course.niveau)
    if not _admin(request.user):
        classes = classes.filter(teacher=request.user)
    classes = list(classes.annotate(eleves=Count('members', filter=Q(members__user__role='student'))).order_by('name'))
    if request.method == 'POST':
        classe = next((c for c in classes if str(c.pk) == request.POST.get('classroom')), None)
        if classe is None:
            messages.error(request, 'Choisissez la classe.')
        else:
            try:
                session = direct.creer(quiz, classe, request.user,
                                       counts_as_attempt=request.POST.get('counts_as_attempt') == '1')
            except direct.ErreurDirect as exc:
                messages.error(request, str(exc))
            else:
                _prevenir_eleves(session)
                return redirect('quizzes:live_host', session.pk)
    return render(request, 'quizzes/live_launch.html', {
        'quiz': quiz, 'classes': classes, 'page_title': f'En direct — {quiz.title}',
    })


def _prevenir_eleves(session):
    from accounts.models import User
    from classrooms.models import ClassroomMember
    from notifications.models import Notification
    ids = ClassroomMember.objects.filter(classroom=session.classroom).values('user_id')
    eleves = User.objects.filter(pk__in=ids, role='student', is_active=True)
    Notification.notify_many(
        eleves, title='Quiz en direct',
        message=f'Rejoins « {session.quiz.title} » maintenant (code {session.code}).',
        type='quiz_assigned', actor=session.host,
        link=reverse('quizzes:live_play', args=[session.pk]), group_key=f'direct:{session.pk}',
    )


@teacher_required
def animer(request, pk):
    session = _session_hote(request, pk)
    return render(request, 'quizzes/live_host.html', {
        'session': session, 'join_url': request.build_absolute_uri(reverse('quizzes:live_join')),
        'page_title': f'En direct — {session.quiz.title}',
    })


@teacher_required
def etat_hote(request, pk):
    session = _session_hote(request, pk)
    return JsonResponse(direct.etat_hote(session), headers={'Cache-Control': 'no-store'})


@require_POST
@teacher_required
def action_hote(request, pk):
    session = _session_hote(request, pk)
    try:
        data = json.loads(request.body.decode('utf-8') or '{}')
    except (json.JSONDecodeError, UnicodeDecodeError):
        data = {}
    try:
        direct.agir(session, data.get('action'))
    except direct.ErreurDirect as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    return JsonResponse(direct.etat_hote(session))


@student_required
def rejoindre(request):
    """Entrer le code projeté, ou choisir une partie ouverte de sa classe."""
    ouvertes = list(direct.parties_ouvertes_pour(request.user))
    if request.method == 'POST':
        code = ''.join(ch for ch in (request.POST.get('code') or '') if ch.isdigit())
        session = LiveSession.objects.filter(code=code).exclude(state=LiveSession.FINI).first()
        if session is None:
            messages.error(request, 'Code inconnu ou partie terminée.')
        else:
            try:
                direct.rejoindre(session, request.user)
            except direct.ErreurDirect as exc:
                messages.error(request, str(exc))
            else:
                return redirect('quizzes:live_play', session.pk)
    return render(request, 'quizzes/live_join.html', {'ouvertes': ouvertes, 'page_title': 'Quiz en direct'})


def _participant(request, pk):
    session = get_object_or_404(LiveSession.objects.select_related('quiz', 'classroom'), pk=pk)
    participant = LiveParticipant.objects.filter(session=session, student=request.user).first()
    return session, participant


@student_required
def jouer(request, pk):
    session, participant = _participant(request, pk)
    if participant is None:
        try:
            participant = direct.rejoindre(session, request.user)
        except direct.ErreurDirect as exc:
            messages.error(request, str(exc))
            return redirect('quizzes:live_join')
    return render(request, 'quizzes/live_play.html', {
        'session': session, 'page_title': f'En direct — {session.quiz.title}',
    })


@student_required
def etat_eleve(request, pk):
    session, participant = _participant(request, pk)
    if participant is None:
        return JsonResponse({'error': 'Rejoins d’abord la partie.'}, status=403)
    return JsonResponse(direct.etat_eleve(session, participant), headers={'Cache-Control': 'no-store'})


@require_POST
@student_required
def repondre(request, pk):
    session, participant = _participant(request, pk)
    if participant is None:
        return JsonResponse({'error': 'Rejoins d’abord la partie.'}, status=403)
    try:
        data = json.loads(request.body.decode('utf-8') or '{}')
        choix = int(data.get('choice'))
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError):
        return JsonResponse({'error': 'Réponse invalide.'}, status=400)
    try:
        direct.repondre(session, participant, choix)
    except direct.ErreurDirect as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    return JsonResponse(direct.etat_eleve(session, participant))
