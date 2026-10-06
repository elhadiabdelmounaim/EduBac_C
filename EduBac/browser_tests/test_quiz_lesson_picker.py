"""Verify that selecting a school level immediately populates the lesson list."""
import os
import shutil

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.management import call_command
from django.urls import reverse
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
