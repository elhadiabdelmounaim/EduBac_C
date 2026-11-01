import shutil
from unittest.mock import patch

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from accounts.models import TeacherProfile, User
from education.models import Course, Lesson
from quizzes.models import Question, Quiz


class QuizQuestionEditingBrowserTests(StaticLiveServerTestCase):
    def test_teacher_can_add_a_question_and_cannot_delete_the_last_one(self):
        teacher = User.objects.create_user(
            username='quiz-edit-browser',
            email='quiz-edit-browser@example.test',
            password='Browser-test-only-123!',
            role='teacher',
        )
        TeacherProfile.objects.get_or_create(user=teacher)
        course = Course.objects.create(name='Mathématiques', niveau='tronc_commun')
        lesson = Lesson.objects.create(course=course, title='Questions éditables', order=1)
        quiz = Quiz.objects.create(
            title='Quiz modifiable', lesson=lesson, created_by=teacher,
            question_count=1, status='draft',
        )
        Question.objects.create(
            quiz=quiz, order=1, text='Question initiale', correct_answer='A',
        )
        self.assertEqual(Question.objects.get(quiz=quiz).points, 1)
        edit_url = self.live_server_url + reverse('quizzes:edit_questions', args=[quiz.pk])

        with patch(
            'ai.services.AIService.generate_quiz_from_lesson',
            side_effect=AssertionError('L’édition d’un quiz ne doit pas appeler l’IA.'),
        ), sync_playwright() as pw:
            browser = pw.chromium.launch(
                executable_path=shutil.which('chromium'),
                headless=True,
                args=['--no-sandbox'],
            )
            try:
                page = browser.new_page(viewport={'width': 1280, 'height': 900})
                page.goto(self.live_server_url + reverse('accounts:login'))
                page.locator('[name="email"]').fill(teacher.email)
                page.locator('[name="password"]').fill('Browser-test-only-123!')
                page.get_by_role('button', name='Se connecter', exact=True).click()
                page.wait_for_url(self.live_server_url + reverse('accounts:dashboard'))
                page.goto(edit_url)
                expect(page.get_by_text('Question 1', exact=True)).to_be_visible()
                points_values = page.locator('input[name$="_points"]').evaluate_all(
                    'fields => fields.map(field => field.value)',
                )
                points_markup = page.locator('input[name$="_points"]').evaluate_all(
                    'fields => fields.map(field => field.outerHTML)',
                )
                self.assertEqual(points_values, ['1.00'], str(points_markup))
                page.get_by_role('button', name='Ajouter une question').first.click()
                expect(page.get_by_text('Question 2', exact=True)).to_be_visible()

                page.get_by_role('button', name='Supprimer la question').last.click()
                expect(page.get_by_text('Question supprimée.', exact=True)).to_be_visible()
            finally:
                browser.close()

        quiz.refresh_from_db()
        self.assertEqual(quiz.questions.count(), 1)
        self.assertTrue(Question.objects.filter(quiz=quiz).exists())
