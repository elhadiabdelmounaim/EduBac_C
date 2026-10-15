import re
import shutil
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse
from playwright.sync_api import sync_playwright, expect

from accounts.models import User, TeacherProfile
from education.models import Course, Lesson
from quizzes.models import Quiz, Question, Choice


class QuizEditReturnBrowserTests(StaticLiveServerTestCase):
    def test_save_and_return_link_keep_same_quiz_and_edited_questions(self):
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            teacher = User.objects.create_user(
                username='edit-browser', email='edit-browser@example.test',
                password='Browser-test-only-123!', role='teacher',
            )
            TeacherProfile.objects.get_or_create(user=teacher)
            course = Course.objects.create(name='Maths', niveau='tronc_commun')
            lesson = Lesson.objects.create(course=course, title='Équations', order=1)
            quiz = Quiz.objects.create(
                title='Quiz conservé après modification', created_by=teacher, lesson=lesson,
                question_count=1, seconds_per_question=35, difficulty='difficile',
            )
            question = Question.objects.create(
                quiz=quiz, text='Résoudre $2x=10$.', correct_answer='5',
            )
            good = Choice.objects.create(question=question, text='5', is_correct=True)
            Choice.objects.create(question=question, text='4')
            preview_url = self.live_server_url + reverse('quizzes:teacher_ai') + f'?quiz={quiz.pk}'
            with sync_playwright() as pw, patch('ai.services.AIService.generate_quiz_from_lesson') as generate:
                browser = pw.chromium.launch(
                    executable_path=shutil.which('chromium'), headless=True, args=['--no-sandbox'],
                )
                try:
                    page = browser.new_page()
                    page.goto(self.live_server_url + reverse('accounts:login'))
                    page.locator('input[name="email"]').fill(teacher.email)
                    page.locator('input[name="password"]').fill('Browser-test-only-123!')
                    page.get_by_role('button', name='Se connecter', exact=True).click()
                    page.wait_for_url(self.live_server_url + reverse('accounts:dashboard'))
                    page.goto(preview_url)
                    page.get_by_role('link', name=re.compile(r'Modifier$')).click()
                    page.locator(f'[name="q_{question.pk}_text"]').fill('Résoudre $2x=12$.')
                    page.locator(f'[name="q_{question.pk}_correct"]').fill('6')
                    page.locator(f'[name="q_{question.pk}_expl"]').fill('DOUZE divisé par deux donne six.')
                    page.locator(f'[name="c_{good.pk}_text"]').fill('6')
                    page.get_by_role('button', name=re.compile(r'Enregistrer$')).click()
                    expect(page).to_have_url(preview_url)
                    expect(page.get_by_text('Questions enregistrées.', exact=True)).to_be_visible()
                    expect(page.locator('.qb-detail-explain')).to_contain_text('DOUZE')
                    expect(page.locator('#secondsPerQ')).to_have_value('35')
                    expect(page.locator('#difficultySelect')).to_have_value('difficile')
                    expect(page.locator('#sendQuizForm')).to_be_visible()
                    page.reload()
                    expect(page.locator('.qb-detail-explain')).to_contain_text('DOUZE')
                    page.get_by_role('link', name=re.compile(r'Modifier$')).click()
                    expect(page.locator(f'[name="q_{question.pk}_correct"]')).to_have_value('6')
                    page.get_by_role('link', name='Retour au quiz', exact=True).click()
                    expect(page).to_have_url(preview_url)
                    expect(page.locator('.qb-detail-explain')).to_contain_text('DOUZE')
                    page.screenshot(path='/tmp/quiz-edit-return.jpg', full_page=True)
                    generate.assert_not_called()
                finally:
                    browser.close()
            quiz.refresh_from_db()
            question.refresh_from_db()
            self.assertEqual(Quiz.objects.count(), 1)
            self.assertEqual(question.correct_answer, '6')
            self.assertEqual(quiz.status, 'draft')
