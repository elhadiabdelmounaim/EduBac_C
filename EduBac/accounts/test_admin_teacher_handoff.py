from django.test import TestCase, override_settings
from django.urls import reverse

from classrooms.models import Classroom
from .models import User


@override_settings(ALLOWED_HOSTS=['testserver', 'localhost', '127.0.0.1'])
class AdminTeacherHandoffTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin_teacher',
            email='admin-teacher@example.test',
            password='AdminPass123!',
            role='student',
            is_staff=True,
            is_superuser=True,
        )
        legacy_teacher = User.objects.create_user(
            username='legacy_teacher_for_admin',
            email='legacy-teacher-admin@example.test',
            password='TeacherPass123!',
            role='teacher',
        )
        Classroom.objects.create(
            name='Classe déjà existante',
            niveau='tronc_commun',
            teacher=legacy_teacher,
        )

    def test_admin_view_site_link_points_to_teacher_area(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse('admin:index'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'<a href="{reverse("admin_teacher_dashboard")}">Voir le site</a>',
        )

    def test_button_handoff_opens_teacher_dashboard_for_same_account(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse('admin_teacher_dashboard'))

        self.assertRedirects(response, reverse('accounts:teacher_portal'))
        self.assertEqual(self.client.session.get('user_id'), self.admin.pk)
        dashboard = self.client.get(response['Location'])
        self.assertEqual(dashboard.status_code, 200)
        self.assertContains(dashboard, 'Tableau de bord')
        self.assertContains(dashboard, 'Classe déjà existante')

    def test_superuser_with_default_student_role_logs_in_as_teacher(self):
        response = self.client.post(
            reverse('accounts:login'),
            {'username': self.admin.username, 'password': 'AdminPass123!'},
        )

        self.assertRedirects(response, reverse('accounts:teacher_portal'))
        self.assertEqual(self.client.session.get('user_id'), self.admin.pk)
        user = User.objects.get(pk=self.admin.pk)
        self.assertTrue(user.is_teacher())
        self.assertFalse(user.is_student())
        self.assertEqual(
            self.client.get(reverse('accounts:teacher_portal')).status_code,
            200,
        )
        profile = self.client.get(reverse('accounts:profile'))
        self.assertContains(profile, 'Rôle :</strong> Enseignant')
        self.assertEqual(User.objects.get(pk=self.admin.pk).role, 'student')

    def test_app_login_can_switch_from_student_session_to_superuser(self):
        student = User.objects.create_user(
            username='already_logged_student',
            email='already-logged@example.test',
            password='StudentPass123!',
            role='student',
        )
        session = self.client.session
        session['user_id'] = student.pk
        session.save()

        response = self.client.post(
            reverse('accounts:login'),
            {'username': self.admin.username, 'password': 'AdminPass123!'},
        )

        self.assertRedirects(response, reverse('accounts:teacher_portal'))
        self.assertEqual(self.client.session.get('user_id'), self.admin.pk)

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
