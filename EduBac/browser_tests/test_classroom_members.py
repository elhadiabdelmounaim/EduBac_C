import shutil

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from accounts.models import User, StudentProfile, TeacherProfile
from classrooms.models import Classroom, ClassroomMember


class ClassroomMemberBrowserTests(StaticLiveServerTestCase):
    def test_select_and_reject_from_class_and_students_pages(self):
        teacher = User.objects.create_user(
            username='roster-teacher', email='roster-teacher@example.test',
            password='Browser-test-only-123!', role='teacher',
        )
        TeacherProfile.objects.create(user=teacher)
        classroom = Classroom.objects.create(name='Classe de test', teacher=teacher)
        students = []
        for index in range(2):
            student = User.objects.create_user(
                username=f'roster-student-{index}', email=f'roster-student-{index}@example.test',
                role='student',
            )
            StudentProfile.objects.create(user=student)
            ClassroomMember.objects.create(classroom=classroom, user=student)
            students.append(student)
        detail_url = self.live_server_url + reverse('classrooms:detail', args=[classroom.pk])
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                executable_path=shutil.which('chromium'), headless=True, args=['--no-sandbox'],
            )
            try:
                page = browser.new_page(viewport={'width': 390, 'height': 900})
                page.goto(self.live_server_url + reverse('accounts:login'))
                page.locator('input[name="email"]').fill(teacher.email)
                page.locator('input[name="password"]').fill('Browser-test-only-123!')
                page.locator('button[type="submit"]').click()
                page.wait_for_url(self.live_server_url + reverse('accounts:dashboard'))
                page.goto(detail_url)
                button = page.locator('#rejectMembersButton')
                expect(button).to_be_disabled()
                page.get_by_role('checkbox', name=f'Sélectionner {students[0].username}', exact=True).check()
                expect(button).to_have_text('Rejeter (1)')
                button.click()
                expect(page.locator('.js-member-select')).to_have_count(1)
                expect(page.get_by_text('Élèves (1)', exact=True)).to_be_visible()
                expect(page.locator('#rejectMembersForm')).not_to_contain_text(students[0].username)
                page.reload()
                expect(page.locator('.js-member-select')).to_have_count(1)
                page.set_viewport_size({'width': 1440, 'height': 900})
                page.goto(self.live_server_url + reverse('classrooms:students'))
                page.locator('#selectAllMembers').check()
                expect(page.locator('#rejectMembersButton')).to_have_text('Rejeter (1)')
                page.locator('#rejectMembersButton').click()
                expect(page.locator('.js-member-select')).to_have_count(0)
                expect(page.get_by_text('Aucun élève dans vos classes.', exact=True)).to_be_visible()
                page.goto(detail_url)
                expect(page.get_by_text('Élèves (0)', exact=True)).to_be_visible()
                expect(page.locator('#rejectMembersButton')).to_be_disabled()
                browser.close()
            finally:
                if browser.is_connected():
                    browser.close()
        self.assertFalse(classroom.members.exists())
        self.assertEqual(User.objects.filter(pk__in=[s.pk for s in students]).count(), 2)
        self.assertEqual(StudentProfile.objects.filter(user__in=students).count(), 2)
