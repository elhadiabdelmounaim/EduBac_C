from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from classrooms.models import Classroom, ClassroomMember
from education.models import Course, Lesson
from .models import Quiz, Question, Choice, QuizAssignment


@override_settings(ALLOWED_HOSTS=['testserver'])
class QuizEditReturnTests(TestCase):
    def setUp(self):
        media = TemporaryDirectory()
        self.addCleanup(media.cleanup)
        settings = override_settings(MEDIA_ROOT=media.name)
        settings.enable()
        self.addCleanup(settings.disable)
        self.teacher = User.objects.create_user(
            username='edit-teacher', email='edit-teacher@example.test', role='teacher',
        )
        self.other = User.objects.create_user(
            username='other-editor', email='other-editor@example.test', role='teacher',
        )
        self.student = User.objects.create_user(
            username='edit-student', email='edit-student@example.test', role='student',
        )
        course = Course.objects.create(name='Mathématiques', niveau='tronc_commun')
        self.lesson = Lesson.objects.create(course=course, title='Équations', order=1)
        self.quiz = Quiz.objects.create(
            title='Quiz à conserver', description='Résoudre des équations.',
            lesson=self.lesson, created_by=self.teacher, question_count=1,
            seconds_per_question=35, difficulty='difficile', status='draft',
        )
        self.question = Question.objects.create(
            quiz=self.quiz, text='Résoudre $2x=10$.', correct_answer='5', explanation='Diviser par deux.',
        )
        self.good = Choice.objects.create(question=self.question, text='5', is_correct=True)
        self.bad = Choice.objects.create(question=self.question, text='4', is_correct=False)
        self.edit_url = reverse('quizzes:edit_questions', args=[self.quiz.pk])
        self.preview_url = f"{reverse('quizzes:teacher_ai')}?quiz={self.quiz.pk}"
        self.payload = {
            'action': 'save', f'q_{self.question.pk}_text': 'Résoudre $2x=12$.',
            f'q_{self.question.pk}_correct': '6',
            f'q_{self.question.pk}_expl': 'On divise douze par deux.',
            f'c_{self.good.pk}_text': '6', f'c_{self.good.pk}_ok': 'on',
            f'c_{self.bad.pk}_text': '5',
        }
        self.login(self.teacher)

    def login(self, user):
        session = self.client.session
        session['user_id'] = user.pk
        session.save()

    @patch('ai.services.AIService.generate_quiz_from_lesson')
    def test_save_returns_to_same_persisted_quiz_with_changes_and_send_form(self, generate):
        response = self.client.post(self.edit_url, self.payload, follow=True)
        self.assertRedirects(response, self.preview_url)
        self.assertEqual(response.context['quiz_created'].pk, self.quiz.pk)
        self.assertContains(response, 'On divise douze par deux.')
        self.assertContains(response, 'Questions enregistrées.')
        self.assertNotContains(response, 'Quiz généré avec succès.')
        self.assertContains(response, 'id="sendQuizForm"')
        self.question.refresh_from_db()
        self.good.refresh_from_db()
        self.quiz.refresh_from_db()
        self.assertEqual(self.question.text, 'Résoudre $2x=12$.')
        self.assertEqual(self.question.correct_answer, '6')
        self.assertEqual(self.good.text, '6')
        self.assertTrue(self.good.is_correct)
        self.assertEqual(self.quiz.status, 'draft')
        self.assertEqual(self.quiz.title, 'Quiz à conserver')
        self.assertEqual(response.context['selected_seconds_per_question'], 35)
        self.assertEqual(response.context['selected_difficulty'], 'difficile')
        self.assertEqual(response.context['selected_question_count'], 1)
        self.assertEqual(response.context['selected_lesson_id'], str(self.lesson.pk))
        self.assertEqual(response.context['quiz_description'], self.quiz.description)
        self.assertEqual(Quiz.objects.count(), 1)
        self.assertEqual(Choice.objects.count(), 2)
        generate.assert_not_called()

    @patch('ai.services.AIService.generate_quiz_from_lesson')
    def test_return_link_and_reload_reopen_quiz_without_regeneration(self, generate):
        self.assertContains(self.client.get(self.edit_url), f'href="{self.preview_url}"')
        for _ in range(2):
            response = self.client.get(self.preview_url)
            self.assertEqual(response.context['quiz_created'].pk, self.quiz.pk)
            self.assertContains(response, self.edit_url)
        self.assertEqual(Quiz.objects.count(), 1)
        generate.assert_not_called()

    def test_saved_quiz_can_still_be_sent_to_teachers_class(self):
        self.client.post(self.edit_url, self.payload)
        classroom = Classroom.objects.create(name='Classe de test', teacher=self.teacher)
        ClassroomMember.objects.create(classroom=classroom, user=self.student)
        response = self.client.post(self.preview_url, {
            'action': 'send', 'quiz_id': self.quiz.pk, 'lesson': self.lesson.pk,
            'niveau': self.lesson.course.niveau, 'classroom': classroom.pk,
        })
        self.assertRedirects(response, reverse('quizzes:manage'))
        self.quiz.refresh_from_db()
        self.assertEqual(self.quiz.status, 'published')
        self.assertEqual(self.quiz.classroom_id, classroom.pk)
        self.assertTrue(QuizAssignment.objects.filter(quiz=self.quiz, student=self.student).exists())
        self.assertEqual(Quiz.objects.count(), 1)
        self.question.refresh_from_db()
        self.assertEqual(self.question.text, 'Résoudre $2x=12$.')

    def test_other_teacher_cannot_restore_or_edit_quiz(self):
        self.login(self.other)
        self.assertEqual(self.client.get(self.preview_url).status_code, 404)
        self.assertRedirects(self.client.post(self.edit_url, self.payload), reverse('quizzes:manage'))
        self.question.refresh_from_db()
        self.assertEqual(self.question.text, 'Résoudre $2x=10$.')

    def test_student_cannot_restore_or_edit_quiz(self):
        self.login(self.student)
        self.assertEqual(self.client.get(self.preview_url).status_code, 302)
        self.assertEqual(self.client.post(self.edit_url, self.payload).status_code, 302)
        self.assertEqual(Quiz.objects.count(), 1)

    def test_missing_or_malformed_quiz_returns_not_found(self):
        for value in ('invalid', '99999999'):
            self.assertEqual(self.client.get(reverse('quizzes:teacher_ai'), {'quiz': value}).status_code, 404)
