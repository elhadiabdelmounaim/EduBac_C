import shutil

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from accounts.models import TeacherProfile, User


class QuizJsonImportFormBrowserTests(StaticLiveServerTestCase):
    def test_creation_page_exposes_json_import_without_internal_generator_controls(self):
        teacher = User.objects.create_user(
            username='json-form-browser',
            email='json-form-browser@example.test',
            password='Browser-test-only-123!',
            role='teacher',
        )
        TeacherProfile.objects.get_or_create(user=teacher)
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
                expect(page.get_by_role(
                    'button', name='Valider et créer le brouillon',
                )).to_be_visible()
                expect(page.locator('#genBtn')).to_have_count(0)
                expect(page.locator('#sourceFileSelect')).to_have_count(0)
                expect(page.locator('#generationMode')).to_have_count(0)
            finally:
                browser.close()
