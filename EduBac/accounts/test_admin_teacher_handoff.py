from django.test import TestCase, override_settings
from django.urls import reverse

from .models import User


@override_settings(ALLOWED_HOSTS=['testserver', 'localhost', '127.0.0.1'])
class AdminTeacherHandoffTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin_teacher',
            email='admin-teacher@example.test',
            password='AdminPass123!',
            role='teacher',
            is_staff=True,
            is_superuser=True,
        )

    def test_admin_index_shows_teacher_area_button(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse('admin:index'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Ouvrir l’espace professeur')
        self.assertContains(response, reverse('admin_teacher_dashboard'))

    def test_button_handoff_opens_teacher_dashboard_for_same_account(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse('admin_teacher_dashboard'))

        self.assertRedirects(response, reverse('accounts:teacher_portal'))
        self.assertEqual(self.client.session.get('user_id'), self.admin.pk)
        dashboard = self.client.get(response['Location'])
        self.assertEqual(dashboard.status_code, 200)
        self.assertContains(dashboard, 'Tableau de bord')

    def test_handoff_requires_staff_teacher_account(self):
        student = User.objects.create_user(
            username='not_admin',
            email='not-admin@example.test',
            password='StudentPass123!',
            role='student',
        )
        self.client.force_login(student)

        response = self.client.get(reverse('admin_teacher_dashboard'))

        self.assertEqual(response.status_code, 403)
        self.assertNotIn('user_id', self.client.session)

    def test_anonymous_user_is_sent_to_admin_login(self):
        response = self.client.get(reverse('admin_teacher_dashboard'))

        self.assertRedirects(response, reverse('admin:login'))
