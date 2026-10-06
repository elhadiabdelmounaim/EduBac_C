from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from education.models import Course, Lesson
from quizzes.models import Quiz


@override_settings(ALLOWED_HOSTS=['testserver', 'localhost', '127.0.0.1'])
class QuizLessonSelectionTests(TestCase):
    def setUp(self):
        self.teacher = User(username='quiz_teacher', email='quiz-teacher@test.com', role='teacher')
        self.teacher.set_password('pass123')
        self.teacher.save()

        self.course = Course.objects.create(
            name='Mathématiques',
            niveau='tronc_commun',
            order=1,
        )
        self.lesson = Lesson.objects.create(
            course=self.course,
            order=1,
            title='Les nombres réels',
            content='Contenu du cours',
        )
        self.other_lesson = Lesson.objects.create(
            course=self.course,
            order=2,
            title='Les polynômes',
            content='Contenu du cours',
        )
        Quiz.objects.create(
            title='Quiz nombres réels',
            lesson=self.lesson,
            created_by=self.teacher,
        )
        Quiz.objects.create(
            title='Quiz polynômes',
            lesson=self.other_lesson,
            created_by=self.teacher,
        )

        self.client.post('/compte/connexion/', {
            'username': self.teacher.username,
            'password': 'pass123',
        })

    def test_my_quizzes_filters_by_selected_lesson(self):
        response = self.client.get(
            reverse('quizzes:manage'),
            {'lesson': self.lesson.pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Choisir une leçon')
        self.assertContains(response, 'Quiz nombres réels')
        self.assertNotContains(response, 'Quiz polynômes')
        self.assertContains(response, f'?lesson={self.lesson.pk}')

    def test_selected_lesson_opens_preselected_in_quiz_generator(self):
        response = self.client.get(
            reverse('quizzes:teacher_ai'),
            {'lesson': self.lesson.pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['selected_niveau'], self.course.niveau)
        self.assertEqual(response.context['selected_lesson_id'], str(self.lesson.pk))
        self.assertContains(
            response,
            f'<option value="{self.lesson.pk}" selected>',
        )
