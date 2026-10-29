"""Real teacher sessions and uploads, isolated from user accounts and documents."""
import json
import shutil
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from accounts.models import User, TeacherProfile
from ai.services import AIService
from education.media_library import chapter_relative
from education.models import Course, Lesson
from quizzes.models import Quiz
from quizzes.test_resources import QUIZ_DATA


@override_settings(QUIZ_SEMANTIC_CHECK_ENABLED=False)
class QuizResourcesBrowserTests(StaticLiveServerTestCase):
    def setUp(self):
        from ai.test_helpers import isolate_protocol_checks
        isolate_protocol_checks(self)
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        settings = override_settings(MEDIA_ROOT=temporary.name)
        settings.enable()
        self.addCleanup(settings.disable)
        self.teacher = User.objects.create_user(
            username='resource-browser-teacher', email='resource-browser@example.test',
            password='Browser-test-only-123!', role='teacher',
        )
        TeacherProfile.objects.get_or_create(user=self.teacher)
        course = Course.objects.create(name='Maths', niveau='tronc_commun')
        self.lesson = Lesson.objects.create(
            course=course, title='Équations pour le test', order=1, content='HIDDEN_CONTENT',
        )
        other = Lesson.objects.create(course=course, title='Autre leçon', order=2)
        self.lesson_id = str(self.lesson.pk)
        self.other_id = str(other.pk)
        folder = Path(temporary.name) / chapter_relative(self.lesson) / 'Sources_IA'
        folder.mkdir(parents=True)
        (folder / 'Règles.txt').write_text('SOURCE_A : résoudre $2x=6$.', encoding='utf-8')
        (folder / 'Méthodes.txt').write_text('SOURCE_B : vérifier la solution.', encoding='utf-8')
        (folder / 'Autre.txt').write_text('UNSELECTED_CONTENT', encoding='utf-8')

    @contextmanager
    def teacher_page(self, width=1280):
        # Seed ORM before Playwright; stop its runtime before Django teardown.
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                executable_path=shutil.which('chromium'), headless=True, args=['--no-sandbox'],
            )
            try:
                page = browser.new_page(viewport={'width': width, 'height': 1100})
                page.goto(self.live_server_url + reverse('accounts:login'))
                page.locator('input[name="email"]').fill(self.teacher.email)
                page.locator('input[name="password"]').fill('Browser-test-only-123!')
                page.get_by_role('button', name='Se connecter', exact=True).click()
                page.wait_for_url(self.live_server_url + reverse('accounts:dashboard'))
                page.goto(self.live_server_url + reverse('quizzes:teacher_ai'))
                page.select_option('#niveauSelect', 'tronc_commun')
                page.select_option('#lessonSelect', self.lesson_id)
                page.locator('#questionCount').fill('1')
                yield page
            finally:
                browser.close()

    def generate(self, page):
        with page.expect_response(lambda response: response.request.method == 'POST'
                                  and '/generer-envoyer/' in response.url):
            page.locator('#genBtn').click()
        expect(page.get_by_text('Quiz généré avec succès.', exact=True)).to_be_visible()

    def test_multiple_resources_and_new_files_reach_ai_and_preserve_form(self):
        with (
            self.teacher_page() as page,
            patch.object(AIService, '_get_provider', return_value=SimpleNamespace(name='test', model='test')),
            patch.object(AIService, '_chat', return_value=json.dumps(QUIZ_DATA)) as chat,
        ):
            source = page.locator('#sourceFileSelect')
            source.select_option(['Règles.txt', 'Méthodes.txt'])
            page.locator('#quizDescription').fill('OBJECTIF_PROF : deux étapes et vérification.')
            page.locator('#quizResourceUploads').set_input_files([
                {'name': 'Fiche.txt', 'mimeType': 'text/plain', 'buffer': b'UPLOAD_A : exercices guides.'},
                {'name': 'Complément.md', 'mimeType': 'text/markdown', 'buffer': b'UPLOAD_B : isoler x.'},
            ])
            page.locator('#secondsPerQ').fill('35')
            self.generate(page)
            expect(source).to_have_values(['Méthodes.txt', 'Règles.txt'])
            expect(page.locator('#quizDescription')).to_have_value('OBJECTIF_PROF : deux étapes et vérification.')
            expect(page.locator('#secondsPerQ')).to_have_value('35')
            expect(page.get_by_text('Fichiers reçus pour cette génération :', exact=True)).to_be_visible()
            prompt = chat.call_args_list[0].args[0][1]['content']
            for marker in ('SOURCE_A', 'SOURCE_B', 'UPLOAD_A', 'UPLOAD_B', 'OBJECTIF_PROF'):
                self.assertIn(marker, prompt)
            self.assertNotIn('HIDDEN_CONTENT', prompt)
            self.assertNotIn('UNSELECTED_CONTENT', prompt)
            for width in (390, 1280):
                page.set_viewport_size({'width': width, 'height': 1100})
                self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'))
                page.locator('#sourceFileSelect').scroll_into_view_if_needed()
                page.screenshot(path=f'/tmp/quiz-resources-{width}.jpg')
            page.evaluate("document.documentElement.setAttribute('data-theme', 'dark')")
            page.screenshot(path='/tmp/quiz-resources-dark.jpg')
        self.assertEqual(Quiz.objects.count(), 1)

    def test_no_resources_generates_from_description(self):
        with (
            self.teacher_page(width=390) as page,
            patch.object(AIService, '_get_provider', return_value=SimpleNamespace(name='test', model='test')),
            patch.object(AIService, '_chat', return_value=json.dumps(QUIZ_DATA)) as chat,
        ):
            expect(page.locator('#clearResources')).to_be_disabled()
            page.locator('#quizDescription').fill('Équations : deux étapes. Aucun fichier nécessaire.')
            self.generate(page)
            prompt = chat.call_args_list[0].args[0][1]['content']
            self.assertIn('Mode sans ressources', prompt)
            self.assertIn('deux étapes', prompt)
            self.assertNotIn('SOURCE_A', prompt)
            self.assertNotIn('HIDDEN_CONTENT', prompt)
        self.assertEqual(Quiz.objects.count(), 1)

    def test_topic_mode_disables_files_and_switching_back_preserves_selection(self):
        with (
            self.teacher_page() as page,
            patch.object(AIService, '_get_provider', return_value=SimpleNamespace(name='test', model='test')),
            patch.object(AIService, '_chat', return_value=json.dumps(QUIZ_DATA)) as chat,
        ):
            page.select_option('#sourceFileSelect', 'Règles.txt')
            page.locator('#quizResourceUploads').set_input_files(
                {'name': 'Unreadable.txt', 'mimeType': 'text/plain', 'buffer': b'\xff'},
            )
            page.select_option('#generationMode', 'topic')
            expect(page.locator('#sourceFileSelect')).to_be_disabled()
            expect(page.locator('#quizResourceUploads')).to_be_disabled()
            page.select_option('#generationMode', 'resources')
            expect(page.locator('#sourceFileSelect')).to_have_values(['Règles.txt'])
            self.assertEqual(page.locator('#quizResourceUploads').evaluate('(input) => input.files.length'), 1)
            page.select_option('#generationMode', 'topic')
            page.locator('#quizSubject').fill('Équations à deux étapes')
            self.generate(page)
            prompt = chat.call_args_list[0].args[0][1]['content']
            self.assertIn('Équations à deux étapes', prompt)
            self.assertNotIn('Unreadable', prompt)
            self.assertNotIn('SOURCE_A', prompt)
        self.assertEqual(Quiz.objects.count(), 1)

    def test_empty_form_and_invalid_upload_show_errors_without_ai_calls(self):
        with self.teacher_page() as page, patch.object(AIService, '_chat') as chat:
            page.locator('#genBtn').click()
            expect(page.locator('#resourceValidationMessage')).to_contain_text('description')
            expect(page.locator('#genBtn')).to_be_enabled()
            page.locator('#quizDescription').fill('Résoudre des équations.')
            page.locator('#quizResourceUploads').set_input_files(
                {'name': 'program.exe', 'mimeType': 'application/octet-stream', 'buffer': b'bad'},
            )
            page.locator('#genBtn').click()
            expect(page.locator('#resourceValidationMessage')).to_contain_text('Format non pris en charge')
            chat.assert_not_called()
            page.locator('#quizResourceUploads').set_input_files(
                {'name': 'Invalid.txt', 'mimeType': 'text/plain', 'buffer': b'\xff'},
            )
            with page.expect_response(lambda response: response.request.method == 'POST'
                                      and '/generer-envoyer/' in response.url):
                page.locator('#genBtn').click()
            expect(page.get_by_role('alert').filter(has_text='Échec de la génération')).to_be_visible()
            expect(page.locator('#quizDescription')).to_have_value('Résoudre des équations.')
            chat.assert_not_called()
        self.assertFalse(Quiz.objects.exists())

    def test_all_clear_and_changing_lesson_remove_invalid_selections(self):
        with self.teacher_page() as page:
            page.locator('#selectAllResources').click()
            expect(page.locator('#sourceFileSelect')).to_have_values(['Autre.txt', 'Méthodes.txt', 'Règles.txt'])
            page.locator('#clearResources').click()
            expect(page.locator('#sourceFileSelect')).to_have_values([])
            page.select_option('#sourceFileSelect', 'Règles.txt')
            page.select_option('#lessonSelect', self.other_id)
            expect(page.locator('#sourceFileSelect')).to_be_disabled()
            page.select_option('#lessonSelect', self.lesson_id)
            expect(page.locator('#sourceFileSelect')).to_have_values([])
