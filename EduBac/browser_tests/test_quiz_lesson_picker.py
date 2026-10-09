"""Verify that selecting a school level immediately populates the lesson list."""
import os
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.management import call_command
from django.urls import reverse
from django.test import override_settings
from playwright.sync_api import expect, sync_playwright

from accounts.models import TeacherProfile, User
from education.curriculum import CURRICULUM
from education.models import Lesson


class QuizLessonPickerBrowserTests(StaticLiveServerTestCase):
    def setUp(self):
        call_command('load_curriculum', verbosity=0)
        self.teacher = User.objects.create_user(
            username='lesson_picker_teacher',
            email='lesson-picker@example.test',
            password='Browser-test-only-123!',
            role='teacher',
        )
        TeacherProfile.objects.get_or_create(user=self.teacher)
        self.expected_lessons_by_niveau = {
            level['code']: list(
                Lesson.objects.filter(course__niveau=level['code'])
                .order_by('order', 'title')
                .values_list('order', 'title')
            )
            for level in CURRICULUM
        }

        from education.media_library import chapter_relative
        self.source_temp = TemporaryDirectory()
        self.addCleanup(self.source_temp.cleanup)
        media_settings = override_settings(MEDIA_ROOT=self.source_temp.name)
        media_settings.enable()
        self.addCleanup(media_settings.disable)
        source_lesson = Lesson.objects.filter(
            course__niveau=CURRICULUM[0]['code'],
        ).order_by('order').first()
        self.source_lesson_id = str(source_lesson.pk)
        self.source_folder = Path(self.source_temp.name) / chapter_relative(source_lesson) / 'Sources_IA'
        self.source_folder.mkdir(parents=True)
        (self.source_folder / 'Règles été.txt').write_text('SOURCE_CHOISIE $x^2$', encoding='utf-8')
        (self.source_folder / 'Autre.txt').write_text('AUTRE_SOURCE', encoding='utf-8')

        self.playwright = sync_playwright().start()
        self.addCleanup(self.playwright.stop)
        executable = os.environ.get('CHROMIUM_EXECUTABLE') or shutil.which('chromium')
        self.browser = self.playwright.chromium.launch(
            executable_path=executable,
            headless=True,
            args=['--no-sandbox'],
        )
        self.addCleanup(self.browser.close)
        self.context = self.browser.new_context()
        self.context.add_init_script(
            "Element.prototype.replaceChildren = undefined;"
        )
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.page.set_default_timeout(10000)

    def log_in_teacher(self):
        response = self.page.goto(
            self.live_server_url + reverse('accounts:login')
        )
        self.assertEqual(response.status, 200)
        self.page.locator('input[name="email"]').fill(self.teacher.email)
        self.page.locator('input[name="password"]').fill('Browser-test-only-123!')
        self.page.get_by_role('button', name='Se connecter', exact=True).click()
        self.page.wait_for_url(lambda url: '/connexion/' not in url)

    def test_source_picker_changes_resets_and_reaches_ai(self):
        from ai.services import AIService
        from ai.test_quiz_novelty import NEW, quiz_json
        self.log_in_teacher()
        self.page.goto(self.live_server_url + reverse('quizzes:teacher_ai'))
        source = self.page.locator('#sourceFileSelect')
        expect(source).to_be_disabled()
        level = CURRICULUM[0]['code']
        self.page.select_option('#niveauSelect', level)
        self.page.select_option('#lessonSelect', self.source_lesson_id)
        expect(source).to_be_enabled()
        self.assertEqual(source.locator('option').all_text_contents(), [
            'Tous les fichiers de la leçon', 'Autre.txt', 'Règles été.txt',
        ])
        source.select_option('Règles été.txt')
        self.page.select_option('#niveauSelect', CURRICULUM[1]['code'])
        expect(source).to_be_disabled()
        expect(source).to_have_value('')
        self.page.select_option('#niveauSelect', level)
        self.page.select_option('#lessonSelect', self.source_lesson_id)
        source.select_option('Règles été.txt')
        self.page.locator('#questionCount').fill('1')
        with (
            patch.object(AIService, '_get_provider', return_value=SimpleNamespace(name='test', model='test')),
            patch.object(AIService, '_chat', return_value=quiz_json([NEW[0]])) as chat,
        ):
            with self.page.expect_navigation(wait_until='domcontentloaded'):
                self.page.locator('#genBtn').click()
            expect(source).to_have_value('Règles été.txt')
            prompt = chat.call_args_list[0].args[0][1]['content']
            self.assertIn('SOURCE_CHOISIE $x^2$', prompt)
            self.assertNotIn('AUTRE_SOURCE', prompt)
        (self.source_folder / 'Règles été.txt').unlink()
        with patch.object(AIService, '_chat') as chat:
            with self.page.expect_navigation(wait_until='domcontentloaded'):
                self.page.locator('#genBtn').click()
            chat.assert_not_called()
            expect(self.page.get_by_text('Le fichier source sélectionné est introuvable', exact=False)).to_be_visible()
            expect(source).to_have_value('')

    def test_repeated_generation_preserves_parameters_and_replaces_duplicates(self):
        from ai.services import AIService
        from ai.test_quiz_novelty import OLD, NEW, quiz_json

        self.log_in_teacher()
        self.page.goto(self.live_server_url + reverse('quizzes:teacher_ai'))
        level = CURRICULUM[0]['code']
        self.page.select_option('#niveauSelect', level)
        lessons = self.page.locator('#lessonSelect')
        expect(lessons).to_be_enabled()
        lesson_id = lessons.locator('option').nth(1).get_attribute('value')
        self.page.select_option('#lessonSelect', lesson_id)
        self.page.select_option('#difficultySelect', 'difficile')
        self.page.locator('#secondsPerQ').fill('35')
        self.page.locator('#questionCount').fill('2')
        description = 'Varier les situations et les raisonnements.'
        self.page.locator('textarea[name="description"]').fill(description)
        self.page.select_option('#aiProviderSelect', 'groq')
        self.page.select_option('#aiModelSelect', 'openai/gpt-oss-20b')

        with (
            patch.object(AIService, '_get_provider', return_value=SimpleNamespace(
                name='groq', model='test-model',
            )),
            patch.object(AIService, '_chat', side_effect=[
                quiz_json(OLD), '{"similar_questions":[]}',
                quiz_json(list(reversed(OLD))), quiz_json(NEW), '{"similar_questions":[]}',
            ]) as chat,
        ):
            for index in range(2):
                with self.page.expect_navigation(wait_until='domcontentloaded'):
                    self.page.locator('#genBtn').click()
                expect(self.page.locator('#niveauSelect')).to_have_value(level)
                expect(self.page.locator('#lessonSelect')).to_have_value(lesson_id)
                expect(self.page.locator('#questionCount')).to_have_value('2')
                expect(self.page.locator('#secondsPerQ')).to_have_value('35')
                expect(self.page.locator('#difficultySelect')).to_have_value('difficile')
                expect(self.page.locator('textarea[name="description"]')).to_have_value(description)
                expect(self.page.locator('#aiProviderSelect')).to_have_value('groq')
                expect(self.page.locator('#aiModelSelect')).to_have_value('openai/gpt-oss-20b')
                question_label = 'Développer et réduire' if index == 0 else 'Une parcelle rectangulaire'
                expect(self.page.get_by_text(question_label, exact=False).first).to_be_visible()
            self.assertEqual(chat.call_count, 5)

    def test_new_quiz_shows_real_lessons_for_each_selected_level(self):
        self.log_in_teacher()

        generator_url = self.live_server_url + reverse('quizzes:teacher_ai')
        response = self.page.goto(
            self.live_server_url + reverse('quizzes:create')
        )
        self.assertEqual(response.status, 200)
        self.assertEqual(self.page.url, generator_url)
        lesson_select = self.page.locator('#lessonSelect')
        expect(lesson_select).to_be_disabled()

        for level in CURRICULUM:
            with self.subTest(level=level['code']):
                self.page.select_option('#niveauSelect', level['code'])
                expect(lesson_select).to_be_enabled()
                self.assertEqual(
                    lesson_select.locator('option').all_text_contents(),
                    ['— Choisir une leçon —']
                    + [
                        f'{order}. {title}'
                        for order, title
                        in self.expected_lessons_by_niveau[level['code']]
                    ],
                )
                self.assertEqual(self.page.url, generator_url)

    def test_mes_quiz_filters_the_lesson_list_by_level(self):
        self.log_in_teacher()

        manage_url = self.live_server_url + reverse('quizzes:manage')
        response = self.page.goto(manage_url)
        self.assertEqual(response.status, 200)
        niveau_select = self.page.locator('#lessonLevelFilter')
        lesson_select = self.page.locator('#lessonFilter')
        expect(lesson_select).to_be_disabled()

        def lesson_option_labels():
            return [
                label.strip()
                for label in lesson_select.locator('option').all_text_contents()
            ]

        first_level = CURRICULUM[0]['code']
        self.page.select_option('#lessonLevelFilter', first_level)
        expect(lesson_select).to_be_enabled()
        self.assertEqual(
            lesson_option_labels(),
            ['Toutes les leçons du niveau']
            + [
                f'{order}. {title}'
                for order, title in self.expected_lessons_by_niveau[first_level]
            ],
        )
        self.assertEqual(self.page.url, manage_url)

        first_lesson_id = lesson_select.locator('option').nth(1).get_attribute('value')
        self.page.select_option('#lessonFilter', first_lesson_id)
        second_level = CURRICULUM[1]['code']
        self.page.select_option('#lessonLevelFilter', second_level)
        expect(lesson_select).to_be_enabled()
        self.assertEqual(lesson_select.input_value(), '')
        self.assertEqual(
            lesson_option_labels(),
            ['Toutes les leçons du niveau']
            + [
                f'{order}. {title}'
                for order, title in self.expected_lessons_by_niveau[second_level]
            ],
        )

        selected_lesson_id = lesson_select.locator('option').nth(1).get_attribute('value')
        self.page.select_option('#lessonFilter', selected_lesson_id)
        self.page.get_by_role('button', name='Afficher', exact=True).click()
        self.page.wait_for_url(
            lambda url: f'niveau={second_level}' in url
            and f'lesson={selected_lesson_id}' in url
        )
        expect(niveau_select).to_have_value(second_level)
        expect(lesson_select).to_have_value(selected_lesson_id)
        self.assertTrue(
            self.page.locator('.btn-edubac').get_attribute('href').endswith(
                f'?lesson={selected_lesson_id}'
            )
        )
