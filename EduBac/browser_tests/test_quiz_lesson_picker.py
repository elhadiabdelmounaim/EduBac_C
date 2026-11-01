import shutil

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from accounts.models import TeacherProfile, User
from education.models import Course, Lesson


class QuizJsonImportFormBrowserTests(StaticLiveServerTestCase):
    def test_creation_page_exposes_json_import_without_internal_generator_controls(self):
        teacher = User.objects.create_user(
            username='json-form-browser',
            email='json-form-browser@example.test',
            password='Browser-test-only-123!',
            role='teacher',
        )
        TeacherProfile.objects.get_or_create(user=teacher)
        common_course = Course.objects.create(
            name='Mathématiques', niveau='tronc_commun',
        )
        common_lesson = Lesson.objects.create(
            course=common_course, title='Les nombres réels', order=1,
        )
        science_course = Course.objects.create(
            name='Mathématiques', niveau='1ere_bac_sc',
        )
        Lesson.objects.create(
            course=science_course, title='Les suites numériques', order=1,
        )
        with sync_playwright() as pw:
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
                expect(page.locator('#quizJsonFile')).to_be_visible()
                expect(page.locator('#quizLevel')).to_be_visible()
                expect(page.locator('#quizCourse')).to_be_visible()
                expect(page.locator('#quizLesson')).to_be_visible()
                page.locator('#quizLevel').select_option('tronc_commun')
                available_courses = page.locator('#quizCourse').evaluate(
                    "select => Array.from(select.options).filter(option => "
                    "option.value && !option.hidden).map(option => option.value)",
                )
                self.assertEqual(available_courses, [str(common_course.pk)])
                page.locator('#quizCourse').select_option(str(common_course.pk))
                available_lessons = page.locator('#quizLesson').evaluate(
                    "select => Array.from(select.options).filter(option => "
                    "option.value && !option.hidden).map(option => option.value)",
                )
                self.assertEqual(available_lessons, [str(common_lesson.pk)])
                expect(page.locator('#quizDurationInput')).to_have_value('20')
                expect(page.locator('#secondsPerQuestion')).to_have_value('20')
                expect(page.get_by_role(
                    'button', name='Valider et créer le brouillon',
                )).to_be_visible()
                expect(page.locator('#genBtn')).to_have_count(0)
                expect(page.locator('#sourceFileSelect')).to_have_count(0)
                expect(page.locator('#generationMode')).to_have_count(0)
            finally:
                browser.close()
