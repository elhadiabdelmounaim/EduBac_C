"""Quiz en direct : lancement, salle d'attente, réponses (points selon la rapidité), passage
automatique aux résultats, sécurité (bonne réponse jamais envoyée avant la fin de la question),
fin de partie et tentatives notées."""
import json
from datetime import timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from classrooms.models import Classroom, ClassroomMember
from education.models import Course, Lesson
from notifications.models import Notification

from .models import Attempt, Choice, LiveAnswer, LiveParticipant, LiveSession, Question, Quiz


@override_settings(ALLOWED_HOSTS=['testserver'])
class QuizDirectTests(TestCase):
    def setUp(self):
        self.prof = User.objects.create_user(username='prof', email='prof@example.test', role='teacher')
        self.autre_prof = User.objects.create_user(username='prof2', email='prof2@example.test', role='teacher')
        course = Course.objects.create(name='Mathématiques', niveau='tronc_commun')
        lesson = Lesson.objects.create(course=course, title='Les réels', order=1, content='')
        self.quiz = Quiz.objects.create(title='Calcul mental', lesson=lesson, created_by=self.prof, seconds_per_question=20)
        self.q1 = Question.objects.create(quiz=self.quiz, order=1, text='2+3 ?', regle='Addition', explanation='2+3=5')
        self.bon1 = Choice.objects.create(question=self.q1, text='5', is_correct=True, order=0)
        self.faux1 = Choice.objects.create(question=self.q1, text='6', is_correct=False, order=1)
        self.q2 = Question.objects.create(quiz=self.quiz, order=2, text='2×3 ?')
        self.bon2 = Choice.objects.create(question=self.q2, text='6', is_correct=True, order=0)
        Choice.objects.create(question=self.q2, text='5', is_correct=False, order=1)
        self.classe = Classroom.objects.create(name='TC1', niveau='tronc_commun', teacher=self.prof)
        self.a = User.objects.create_user(username='a', email='a@example.test', role='student', first_name='Amal')
        self.b = User.objects.create_user(username='b', email='b@example.test', role='student', first_name='Badr')
        self.x = User.objects.create_user(username='x', email='x@example.test', role='student')
        for e in (self.a, self.b):
            ClassroomMember.objects.create(classroom=self.classe, user=e)

    def connecter(self, user):
        session = self.client.session
        session['user_id'] = user.pk
        session.save()

    def post(self, url, data=None):
        return self.client.post(url, json.dumps(data or {}), content_type='application/json')

    def lancer(self, **extra):
        self.connecter(self.prof)
        self.client.post(reverse('quizzes:live_launch', args=[self.quiz.pk]), {'classroom': self.classe.pk, **extra})
        return LiveSession.objects.latest('pk')

    def action(self, session, action):
        self.connecter(self.prof)
        return self.post(reverse('quizzes:live_host_action', args=[session.pk]), {'action': action})

    def etat(self, session, user):
        self.connecter(user)
        return self.client.get(reverse('quizzes:live_state', args=[session.pk])).json()

    def repondre(self, session, user, choix):
        self.connecter(user)
        return self.post(reverse('quizzes:live_answer', args=[session.pk]), {'choice': choix.pk})

    def rejoindre(self, session, *eleves):
        for e in eleves:
            self.connecter(e)
            self.client.get(reverse('quizzes:live_play', args=[session.pk]))

    def test_lancement_code_et_notification(self):
        session = self.lancer()
        self.assertEqual(len(session.code), 6)
        self.assertEqual(session.state, LiveSession.ATTENTE)
        self.assertEqual(set(Notification.objects.filter(title='Quiz en direct').values_list('recipient__username', flat=True)),
                         {'a', 'b'})
        page = self.client.get(reverse('quizzes:live_host', args=[session.pk]))
        self.assertContains(page, session.code[:3])

    def test_rejoindre_par_code_et_classe_reservee(self):
        session = self.lancer()
        self.connecter(self.a)
        r = self.client.post(reverse('quizzes:live_join'), {'code': session.code[:3] + ' ' + session.code[3:]})
        self.assertRedirects(r, reverse('quizzes:live_play', args=[session.pk]), fetch_redirect_response=False)
        self.connecter(self.x)
        self.client.post(reverse('quizzes:live_join'), {'code': session.code})
        self.assertFalse(LiveParticipant.objects.filter(student=self.x).exists())
        self.assertEqual(self.client.get(reverse('quizzes:live_state', args=[session.pk])).status_code, 403)
        # Le tableau de bord de l'élève propose la partie.
        self.connecter(self.b)
        self.assertContains(self.client.get(reverse('accounts:dashboard')), 'Quiz en direct')

    def test_deroule_points_et_securite(self):
        session = self.lancer()
        self.rejoindre(session, self.a, self.b)
        self.assertEqual(self.action(session, 'demarrer').json()['state'], 'question')
        # Pendant la question : aucun indice de la bonne réponse, ni côté élève ni côté écran.
        eleve = self.etat(session, self.a)
        self.assertTrue(all('correct' not in c for c in eleve['question']['choices']))
        self.connecter(self.prof)
        hote = self.client.get(reverse('quizzes:live_host_state', args=[session.pk])).json()
        self.assertTrue(all('correct' not in c and 'count' not in c for c in hote['question']['choices']))
        # Bonne réponse rapide : plus de 500 points ; fausse : 0 ; pas deux réponses.
        r = self.repondre(session, self.a, self.bon1).json()
        self.assertGreater(r['answer']['points'], 900)
        self.assertEqual(self.repondre(session, self.a, self.faux1).status_code, 400)
        self.repondre(session, self.b, self.faux1)
        # Tout le monde a répondu : résultats affichés d'eux-mêmes.
        self.connecter(self.prof)
        hote = self.client.get(reverse('quizzes:live_host_state', args=[session.pk])).json()
        self.assertEqual(hote['state'], 'resultats')
        compte = {c['text']: c['count'] for c in hote['question']['choices']}
        self.assertEqual(compte, {'5': 1, '6': 1})
        self.assertEqual(hote['leaderboard'][0]['name'], 'Amal')
        self.assertEqual(self.etat(session, self.b)['rank'], 2)
        # Question suivante ; « suivant » pendant une question est refusé ; puis fin.
        self.assertEqual(self.action(session, 'suivant').json()['index'], 1)
        self.assertEqual(self.action(session, 'suivant').status_code, 400)
        self.action(session, 'reveler')
        self.assertEqual(self.action(session, 'suivant').json()['state'], 'fini')

    def test_temps_ecoule(self):
        session = self.lancer()
        self.rejoindre(session, self.a)
        self.action(session, 'demarrer')
        LiveSession.objects.filter(pk=session.pk).update(question_started_at=timezone.now() - timedelta(seconds=30))
        self.assertEqual(self.repondre(session, self.a, self.bon1).status_code, 400)
        self.assertEqual(self.etat(session, self.a)['state'], 'resultats')
        self.assertFalse(LiveAnswer.objects.exists())

    def test_fin_avec_tentatives_notees(self):
        session = self.lancer(counts_as_attempt='1')
        self.rejoindre(session, self.a, self.b)
        self.action(session, 'demarrer')
        self.repondre(session, self.a, self.bon1)
        self.repondre(session, self.b, self.faux1)
        self.action(session, 'suivant')
        self.repondre(session, self.a, self.bon2)
        self.action(session, 'reveler')
        self.assertEqual(self.action(session, 'suivant').json()['state'], 'fini')
        scores = dict(Attempt.objects.values_list('student__username', 'score'))
        self.assertEqual(scores, {'a': 100.0, 'b': 0.0})
        self.assertEqual(self.etat(session, self.a)['rank'], 1)
        # Révision des erreurs de Badr : la question ratée.
        self.connecter(self.b)
        self.assertContains(self.client.get(reverse('quizzes:review_mistakes')), '2+3 ?')

    def test_sans_tentatives_mais_erreurs_a_revoir(self):
        session = self.lancer()
        self.rejoindre(session, self.b)
        self.action(session, 'demarrer')
        self.repondre(session, self.b, self.faux1)
        self.action(session, 'terminer')
        self.assertFalse(Attempt.objects.exists())
        self.connecter(self.b)
        self.assertContains(self.client.get(reverse('quizzes:review_mistakes')), '2+3 ?')

    def test_droits(self):
        session = self.lancer()
        self.connecter(self.autre_prof)
        self.assertEqual(self.client.get(reverse('quizzes:live_host', args=[session.pk])).status_code, 404)
        self.assertEqual(self.post(reverse('quizzes:live_host_action', args=[session.pk]), {'action': 'demarrer'}).status_code, 404)
        self.connecter(self.a)
        self.assertNotEqual(self.post(reverse('quizzes:live_host_action', args=[session.pk]), {'action': 'demarrer'}).status_code, 200)
        session.refresh_from_db()
        self.assertEqual(session.state, LiveSession.ATTENTE)

    def test_une_seule_partie_ouverte_par_classe(self):
        premiere = self.lancer()
        seconde = self.lancer()
        premiere.refresh_from_db()
        self.assertEqual(premiere.state, LiveSession.FINI)
        self.assertNotEqual(seconde.pk, premiere.pk)
