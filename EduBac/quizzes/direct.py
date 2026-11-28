"""Quiz en direct : déroulé de la partie, points, données pour l'écran projeté et les téléphones.

États : attente → question → résultats → question suivante … → fini. Le passage de « question »
à « résultats » se fait tout seul quand le temps est écoulé ou que tout le monde a répondu
(vérifié à chaque interrogation : pas de tâche de fond, ce qui convient à PythonAnywhere)."""
import random
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from .models import Attempt, LiveAnswer, LiveParticipant, LiveSession, StudentAnswer

POINTS_BASE = 500
POINTS_VITESSE = 500
DELAI_GRACE = timedelta(seconds=1)          # latence du réseau
COULEURS = ['rouge', 'bleu', 'jaune', 'vert', 'violet', 'orange']


class ErreurDirect(ValueError):
    pass


def nouveau_code():
    actifs = set(LiveSession.objects.exclude(state=LiveSession.FINI).values_list('code', flat=True))
    while True:
        code = f'{random.randint(0, 999999):06d}'
        if code not in actifs:
            return code


def creer(quiz, classroom, host, counts_as_attempt=False):
    if not quiz.questions.exists():
        raise ErreurDirect('Ce quiz n’a aucune question.')
    # Une seule partie ouverte par classe : l'ancienne est close.
    for ancienne in LiveSession.objects.filter(classroom=classroom).exclude(state=LiveSession.FINI):
        terminer(ancienne)
    return LiveSession.objects.create(
        quiz=quiz, classroom=classroom, host=host, code=nouveau_code(),
        seconds=max(5, min(quiz.seconds_per_question or 20, 300)), counts_as_attempt=counts_as_attempt,
    )


def questions(session):
    if not hasattr(session, '_questions'):
        session._questions = list(session.quiz.get_questions().prefetch_related('choices'))
    return session._questions


def question_courante(session):
    liste = questions(session)
    if session.state in (LiveSession.QUESTION, LiveSession.RESULTATS) and 0 <= session.question_index < len(liste):
        return liste[session.question_index]
    return None


def temps_restant(session, maintenant=None):
    if session.state != LiveSession.QUESTION or not session.question_started_at:
        return 0
    fin = session.question_started_at + timedelta(seconds=session.seconds)
    return max(0.0, (fin - (maintenant or timezone.now())).total_seconds())


def actualiser(session):
    """Question en cours dont le temps est écoulé, ou à laquelle tous ont répondu → résultats."""
    if session.state != LiveSession.QUESTION:
        return session
    question = question_courante(session)
    fini = temps_restant(session) <= 0
    if not fini and question is not None:
        inscrits = session.participants.count()
        repondu = LiveAnswer.objects.filter(participant__session=session, question=question).count()
        fini = inscrits > 0 and repondu >= inscrits
    if fini:
        LiveSession.objects.filter(pk=session.pk, state=LiveSession.QUESTION).update(state=LiveSession.RESULTATS)
        session.state = LiveSession.RESULTATS
    return session


def agir(session, action):
    """Commandes du professeur : demarrer, reveler, suivant, terminer."""
    actualiser(session)
    nb = len(questions(session))
    if action == 'terminer':
        terminer(session)
    elif action == 'reveler' and session.state == LiveSession.QUESTION:
        session.state = LiveSession.RESULTATS
        session.save(update_fields=['state'])
    elif action in ('demarrer', 'suivant') and session.state in (LiveSession.ATTENTE, LiveSession.RESULTATS):
        suivante = session.question_index + 1
        if suivante >= nb:
            terminer(session)
        else:
            session.question_index = suivante
            session.state = LiveSession.QUESTION
            session.question_started_at = timezone.now()
            session.save(update_fields=['question_index', 'state', 'question_started_at'])
    else:
        raise ErreurDirect('Action impossible à ce moment de la partie.')
    return session


def rejoindre(session, eleve):
    if session.state == LiveSession.FINI:
        raise ErreurDirect('Cette partie est terminée.')
    from classrooms.models import ClassroomMember
    if not ClassroomMember.objects.filter(classroom=session.classroom, user=eleve).exists():
        raise ErreurDirect('Cette partie est réservée à une autre classe.')
    participant, _ = LiveParticipant.objects.get_or_create(session=session, student=eleve)
    return participant


def repondre(session, participant, choice_id):
    actualiser(session)
    question = question_courante(session)
    if session.state != LiveSession.QUESTION or question is None:
        raise ErreurDirect('Trop tard : la réponse est déjà affichée.')
    choix = next((c for c in question.choices.all() if c.pk == choice_id), None)
    if choix is None:
        raise ErreurDirect('Choix inconnu.')
    maintenant = timezone.now()
    ecoule = (maintenant - session.question_started_at).total_seconds()
    if maintenant > session.question_started_at + timedelta(seconds=session.seconds) + DELAI_GRACE:
        raise ErreurDirect('Temps écoulé.')
    points = 0
    if choix.is_correct:
        points = POINTS_BASE + round(POINTS_VITESSE * max(0.0, 1 - ecoule / session.seconds))
    try:
        with transaction.atomic():
            LiveAnswer.objects.create(participant=participant, question=question, choice=choix,
                                      is_correct=choix.is_correct, points=points)
            if points:
                LiveParticipant.objects.filter(pk=participant.pk).update(score=F('score') + points)
    except IntegrityError:
        raise ErreurDirect('Tu as déjà répondu à cette question.') from None
    actualiser(session)
    return choix.is_correct, points


def terminer(session):
    if session.state == LiveSession.FINI:
        return session
    session.state = LiveSession.FINI
    session.ended_at = timezone.now()
    session.save(update_fields=['state', 'ended_at'])
    if session.counts_as_attempt:
        _enregistrer_tentatives(session)
    return session


def _enregistrer_tentatives(session):
    """Une tentative notée par élève (score en %), avec ses réponses : résultats et révision."""
    liste = questions(session)
    if not liste:
        return
    for participant in session.participants.select_related('student'):
        reponses = {r.question_id: r for r in participant.answers.select_related('choice')}
        tentative = Attempt.objects.create(quiz=session.quiz, student=participant.student, submitted_at=session.ended_at)
        justes = 0
        for q in liste:
            r = reponses.get(q.pk)
            juste = bool(r and r.is_correct)
            justes += juste
            StudentAnswer.objects.create(attempt=tentative, question=q, answer=(r.choice.text if r and r.choice else ''),
                                         is_correct=juste, explanation=q.explanation)
        tentative.score = round(100 * justes / len(liste), 1)
        tentative.save(update_fields=['score'])


# ---------- Données envoyées aux écrans ----------

def _choix(question, reveler, compter=None):
    lignes = []
    for i, c in enumerate(question.get_choices()):
        ligne = {'id': c.pk, 'text': c.text, 'couleur': COULEURS[i % len(COULEURS)], 'lettre': 'ABCDEF'[i % 6]}
        if reveler:
            ligne['correct'] = c.is_correct
        if compter is not None:
            ligne['count'] = compter.get(c.pk, 0)
        lignes.append(ligne)
    return lignes


def classement(session, n=None):
    lignes = [{'name': p.student.get_full_name() or p.student.username, 'score': p.score, 'id': p.student_id}
              for p in session.participants.select_related('student').order_by('-score', 'joined_at')]
    return lignes[:n] if n else lignes


def etat_hote(session):
    actualiser(session)
    liste = questions(session)
    q = question_courante(session)
    data = {
        'state': session.state, 'code': session.code, 'index': session.question_index, 'total': len(liste),
        'participants': session.participants.count(), 'remaining': round(temps_restant(session), 1),
        'seconds': session.seconds,
    }
    if q is not None:
        reponses = LiveAnswer.objects.filter(participant__session=session, question=q)
        data['answered'] = reponses.count()
        reveler = session.state == LiveSession.RESULTATS
        compter = {}
        if reveler:
            for cid in reponses.values_list('choice_id', flat=True):
                compter[cid] = compter.get(cid, 0) + 1
        data['question'] = {'text': q.text, 'choices': _choix(q, reveler, compter if reveler else None),
                            'regle': q.regle if reveler else '', 'solution': q.explanation if reveler else ''}
    if session.state in (LiveSession.RESULTATS, LiveSession.FINI):
        data['leaderboard'] = classement(session, None if session.state == LiveSession.FINI else 5)
    if session.state == LiveSession.ATTENTE:
        data['joined'] = [p['name'] for p in classement(session)]
    return data


def etat_eleve(session, participant):
    actualiser(session)
    liste = questions(session)
    q = question_courante(session)
    data = {'state': session.state, 'index': session.question_index, 'total': len(liste),
            'remaining': round(temps_restant(session), 1), 'seconds': session.seconds,
            'score': LiveParticipant.objects.filter(pk=participant.pk).values_list('score', flat=True).first() or 0}
    if q is not None:
        reponse = participant.answers.filter(question=q).first()
        reveler = session.state == LiveSession.RESULTATS
        data['question'] = {'id': q.pk, 'text': q.text, 'choices': _choix(q, reveler)}
        data['answer'] = ({'choice': reponse.choice_id, 'correct': reponse.is_correct, 'points': reponse.points}
                          if reponse else None)
    if session.state in (LiveSession.RESULTATS, LiveSession.FINI):
        tous = classement(session)
        rang = next((i + 1 for i, l in enumerate(tous) if l['id'] == participant.student_id), None)
        data['rank'] = rang
        data['players'] = len(tous)
        if session.state == LiveSession.FINI:
            data['podium'] = tous[:3]
    return data


def parties_ouvertes_pour(eleve):
    """Parties en cours des classes de l'élève (lancées il y a moins de 3 heures)."""
    from classrooms.models import ClassroomMember
    classes = ClassroomMember.objects.filter(user=eleve).values('classroom_id')
    return LiveSession.objects.filter(
        classroom_id__in=classes, created_at__gte=timezone.now() - timedelta(hours=3),
    ).exclude(state=LiveSession.FINI).select_related('quiz', 'classroom')
