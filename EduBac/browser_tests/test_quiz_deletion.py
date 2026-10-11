import shutil

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from accounts.models import User, TeacherProfile
from education.models import Course, Lesson
from quizzes.models import Quiz


class QuizDeletionBrowserTests(StaticLiveServerTestCase):
    def test_current_and_legacy_quiz_deletion_requires_confirmation(self):
        teacher = User.objects.create_user(
            username='browser-delete-teacher', email='browser-delete@example.test',
            password='Browser-test-only-123!', role='teacher',
        )
        TeacherProfile.objects.create(user=teacher)
        course = Course.objects.create(name='Test', niveau='tronc_commun')
        lesson = Lesson.objects.create(course=course, title='Leçon conservée')
        current = Quiz.objects.create(
            title='Quiz récent à supprimer', lesson=lesson, created_by=teacher, status='published',
        )
        legacy = Quiz.objects.create(title='Ancien quiz à supprimer', lesson=lesson, status='archived')
        manage_url = self.live_server_url + reverse('quizzes:manage')
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                executable_path=shutil.which('chromium'), headless=True, args=['--no-sandbox'],
            )
            try:
                page = browser.new_page(viewport={'width': 1440, 'height': 900})
                page.goto(self.live_server_url + reverse('accounts:login'))
                page.locator('input[name="email"]').fill(teacher.email)
                page.locator('input[name="password"]').fill('Browser-test-only-123!')
                page.get_by_role('button', name='Se connecter', exact=True).click()
                page.wait_for_url(self.live_server_url + reverse('accounts:dashboard'))
                page.goto(manage_url)
                page.get_by_role('link', name=f'Supprimer le quiz {current.title}', exact=True).click()
                expect(page.get_by_text('Cette action est définitive et ne peut pas être annulée.')).to_be_visible()
                page.get_by_role('link', name='Annuler', exact=True).click()
                expect(page.get_by_role('link', name=f'Supprimer le quiz {current.title}', exact=True)).to_be_visible()
                for quiz, width in ((legacy, 390), (current, 1440)):
                    page.set_viewport_size({'width': width, 'height': 900})
                    page.get_by_role('link', name=f'Supprimer le quiz {quiz.title}', exact=True).click()
                    page.get_by_role('button', name='Supprimer définitivement', exact=True).click()
                    expect(page).to_have_url(self.live_server_url + reverse('quizzes:delete', args=[quiz.pk]))
                    expect(page.locator('#confirmQuizDeletion')).not_to_be_checked()
                    page.locator('#confirmQuizDeletion').check()
                    page.get_by_role('button', name='Supprimer définitivement', exact=True).click()
                    expect(page).to_have_url(manage_url)
                    expect(page.get_by_role('link', name=f'Supprimer le quiz {quiz.title}', exact=True)).to_have_count(0)
                page.reload()
                expect(page.get_by_role('link', name=f'Supprimer le quiz {current.title}', exact=True)).to_have_count(0)
            finally:
                browser.close()
        self.assertFalse(Quiz.objects.filter(pk__in=[current.pk, legacy.pk]).exists())
        self.assertTrue(Lesson.objects.filter(pk=lesson.pk).exists())
