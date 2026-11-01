import json
import shutil
from unittest.mock import patch

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from accounts.models import TeacherProfile, User
from education.models import Course, Lesson
from quizzes.models import Quiz


class QuizJsonValidationBrowserTests(StaticLiveServerTestCase):
    def test_invalid_json_is_rejected_without_creating_a_quiz_or_calling_ai(self):
        teacher = User.objects.create_user(
            username='json-invalid-browser',
            email='json-invalid-browser@example.test',
            password='Browser-test-only-123!',
            role='teacher',
        )
        TeacherProfile.objects.get_or_create(user=teacher)
        course = Course.objects.create(name='Mathématiques', niveau='tronc_commun')
        lesson = Lesson.objects.create(course=course, title='Calculs', order=1)
        invalid_document = {
            'quiz': {
                'title': 'Quiz invalide',
                'level': 'TCS',
                'lesson': lesson.title,
                'duration': 20,
                'questions': [{
                    'id': 'Q1',
                    'type': 'multiple_choice',
                    'statement': 'Calculer $2+2$.',
                    'correct_answer': 'INCONNU',
                    'difficulty': 'easy',
                    'points': 1,
                    'choices': [
                        {'id': 'A', 'text': '4'}, {'id': 'B', 'text': '3'},
                        {'id': 'C', 'text': '5'}, {'id': 'D', 'text': '6'},
                    ],
                }],
            },
        }
        with patch(
            'ai.services.AIService.generate_quiz_from_lesson',
            side_effect=AssertionError('Un import JSON ne doit pas appeler l’IA.'),
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
                page.goto(self.live_server_url + reverse('quizzes:teacher_ai'))
                page.locator('#quizJsonFile').set_input_files({
                    'name': 'quiz-invalide.json',
                    'mimeType': 'application/json',
                    'buffer': json.dumps(invalid_document).encode('utf-8'),
                })
                page.get_by_role('button', name='Valider et créer le brouillon').click()
                expect(page.get_by_text(
                    'la bonne réponse ne correspond à aucun identifiant de choix',
                    exact=False,
                )).to_be_visible()
            finally:
                browser.close()

        self.assertFalse(Quiz.objects.exists())
