"""Outils du professeur : publication programmée vers plusieurs classes, prompt pour une IA,
analyse des réponses (erreur la plus fréquente, fiche du cours à revoir)."""
from datetime import timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from classrooms.models import Classroom, ClassroomMember
from education.models import Course, Lesson

from .models import Attempt, Choice, Question, Quiz, QuizAssignment, StudentAnswer
from .prompt_ia import construire_prompt, latex_standard
from .views import _publish_scheduled_quizzes


@override_settings(ALLOWED_HOSTS=['testserver'])
class OutilsProfesseurTests(TestCase):
    def setUp(self):
        self.prof = User.objects.create_user(username='prof', email='prof@example.test', role='teacher')
        course = Course.objects.create(name='Mathématiques', niveau='1ere_bac_sc')
        # Leçon 4 de 1ère Bac Sciences : elle a un cours en ligne (plan et règles).
        self.lesson = Lesson.objects.create(course=course, title='Le produit scalaire dans le plan', order=4, content='')
        self.quiz = Quiz.objects.create(title='Produit scalaire', lesson=self.lesson, created_by=self.prof)
        self.q1 = Question.objects.create(quiz=self.quiz, order=1, text='Calculer $\\vec u\\cdot\\vec v$.',
                                          regle='Expression analytique du produit scalaire dans un repère orthonormé.')
        for i, (texte, ok) in enumerate([('3', True), ('5', False), ('0', False)]):
            Choice.objects.create(question=self.q1, text=texte, is_correct=ok, order=i)
        self.classes = []
        for nom in ('1bac1', '1bac2'):
            classe = Classroom.objects.create(name=nom, niveau='1ere_bac_sc', teacher=self.prof)
            eleve = User.objects.create_user(username=f'e-{nom}', email=f'{nom}@example.test', role='student')
            ClassroomMember.objects.create(classroom=classe, user=eleve)
            self.classes.append(classe)
        session = self.client.session
        session['user_id'] = self.prof.pk
        session.save()

    # ---------- Publication programmée ----------
    def test_programmer_pour_deux_classes(self):
        self.client.post(reverse('quizzes:schedule', args=[self.quiz.pk]), {
            'publish_at': '2030-01-01T08:00', 'classroom': [c.pk for c in self.classes]})
        self.quiz.refresh_from_db()
        self.assertEqual(set(self.quiz.scheduled_classrooms.all()), set(self.classes))
        page = self.client.get(reverse('quizzes:schedule', args=[self.quiz.pk])).content.decode()
        for c in self.classes:
            self.assertIn(f'value="{c.pk}" id="scheduleClass{c.pk}" checked', page)
        Quiz.objects.filter(pk=self.quiz.pk).update(publish_at=timezone.now() - timedelta(minutes=1))
        _publish_scheduled_quizzes()
        self.quiz.refresh_from_db()
        self.assertEqual(self.quiz.status, 'published')
        self.assertEqual(QuizAssignment.objects.filter(quiz=self.quiz).count(), 2)

    def test_programmation_annulee_vide_les_classes(self):
        self.client.post(reverse('quizzes:schedule', args=[self.quiz.pk]), {
            'publish_at': '2030-01-01T08:00', 'classroom': [self.classes[0].pk]})
        self.client.post(reverse('quizzes:schedule', args=[self.quiz.pk]), {'publish_at': ''})
        self.assertFalse(self.quiz.scheduled_classrooms.exists())

    def test_ancienne_programmation_sans_classes_cochees(self):
        Quiz.objects.filter(pk=self.quiz.pk).update(
            classroom=self.classes[1], publish_at=timezone.now() - timedelta(minutes=1))
        _publish_scheduled_quizzes()
        self.assertEqual(list(QuizAssignment.objects.values_list('student__username', flat=True)), ['e-1bac2'])

    # ---------- Prompt pour une IA ----------
    def test_prompt_avec_plan_regles_et_format(self):
        prompt = construire_prompt(self.lesson, nombre=8, difficulte='hard')
        self.assertIn('8 questions', prompt)
        self.assertIn('Le produit scalaire dans le plan', prompt)
        self.assertIn('1ère Bac Sciences', prompt)
        self.assertIn('"explication"', prompt)
        self.assertIn('"regle"', prompt)
        self.assertIn('Plan de la leçon', prompt)
        self.assertIn('Règles du cours', prompt)
        self.assertNotIn('\\vect{', prompt)              # macros du cours traduites
        self.assertIn('difficiles (hard)', prompt)

    def test_latex_standard(self):
        self.assertEqual(latex_standard(r'\vect{AB}\cdot\vu \Cc \R'),
                         r'\overrightarrow{AB}\cdot\overrightarrow{u} (\mathcal{C}) \mathbb{R}')

    def test_prompt_vue(self):
        url = reverse('quizzes:ai_prompt')
        self.assertEqual(self.client.get(url).status_code, 400)
        donnees = self.client.get(url, {'lesson': self.lesson.pk, 'n': '12'}).json()
        self.assertIn('12 questions', donnees['prompt'])
        page = self.client.get(reverse('quizzes:teacher_ai'))
        self.assertContains(page, 'Préparer le prompt pour une IA')
        # Réservé aux professeurs.
        session = self.client.session
        session['user_id'] = User.objects.get(username='e-1bac1').pk
        session.save()
        self.assertNotEqual(self.client.get(url, {'lesson': self.lesson.pk}).status_code, 200)

    # ---------- Analyse des réponses ----------
    def test_analyse_erreur_frequente_et_lien_cours(self):
        for i, reponse in enumerate(['5', '5', '3', '0']):
            eleve = User.objects.create_user(username=f'x{i}', email=f'x{i}@example.test', role='student')
            attempt = Attempt.objects.create(quiz=self.quiz, student=eleve)
            StudentAnswer.objects.create(attempt=attempt, question=self.q1, answer=reponse, is_correct=reponse == '3')
        page = self.client.get(reverse('quizzes:question_stats', args=[self.quiz.pk]))
        self.assertContains(page, '25 %')
        self.assertContains(page, 'À reprendre en classe')
        self.assertContains(page, '(2 élèves)')
        self.assertRegex(page.content.decode(), reverse('education:lesson_course_html', args=[self.lesson.pk]) + r'#s\d+')
