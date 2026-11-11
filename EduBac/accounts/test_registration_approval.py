from django.test import Client, TestCase, override_settings
from django.urls import reverse

from classrooms.models import Classroom, ClassroomMember
from .models import StudentProfile, User


@override_settings(ALLOWED_HOSTS=['testserver', 'localhost', '127.0.0.1'])
class StudentRegistrationApprovalTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.classroom = Classroom.objects.create(
            name='Classe de test',
            niveau='tronc_commun',
            code='TEST2026',
        )

    def payload(self, **overrides):
        data = {
            'name': 'Amina El Amrani',
            'username': 'amina_2026',
            'password': 'LongPass123!',
            'password2': 'LongPass123!',
            'class_code': self.classroom.code,
        }
        data.update(overrides)
        return data

    def login_with_session(self, user, client=None):
        client = client or self.client
        session = client.session
        session['user_id'] = user.pk
        session['role'] = user.role
        session.save()

    def test_registration_form_uses_username_and_has_no_email_field(self):
        response = self.client.get(reverse('accounts:register_student'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="username"')
        self.assertContains(response, 'name="class_code"')
        self.assertNotContains(response, 'name="email"')
        self.assertNotContains(response, 'name="niveau"')

    def test_valid_registration_creates_inactive_pending_student_and_membership(self):
        response = self.client.post(
            reverse('accounts:register_student'),
            self.payload(class_code='test2026'),
        )

        self.assertRedirects(response, reverse('accounts:login'))
        user = User.objects.get(username='amina_2026')
        self.assertEqual(user.get_full_name(), 'Amina El Amrani')
        self.assertEqual(user.role, 'student')
        self.assertIsNone(user.email)
        self.assertEqual(user.approval_status, 'pending')
        self.assertFalse(user.is_active)
        self.assertTrue(user.email_verified)
        self.assertEqual(user.student_profile.niveau, self.classroom.niveau)
        self.assertTrue(
            ClassroomMember.objects.filter(
                classroom=self.classroom,
                user=user,
            ).exists()
        )
        self.assertNotIn('user_id', self.client.session)

    def test_invalid_or_disabled_class_code_never_creates_an_account(self):
        response = self.client.post(
            reverse('accounts:register_student'),
            self.payload(class_code='NOTREAL'),
        )
        self.assertContains(
            response,
            'Classe introuvable. Veuillez vérifier le code de classe et réessayer.',
        )
        self.assertFalse(User.objects.filter(username='amina_2026').exists())

        self.classroom.is_active = False
        self.classroom.save(update_fields=['is_active'])
        response = self.client.post(
            reverse('accounts:register_student'),
            self.payload(),
        )
        self.assertEqual(
            response.context['error'],
            "Ce code de classe n'est plus actif. Veuillez contacter l'administrateur.",
        )
        self.assertFalse(User.objects.filter(username='amina_2026').exists())

    def test_duplicate_username_is_rejected_without_changing_existing_account(self):
        existing = User.objects.create_user(
            username='amina_2026',
            email='legacy@example.test',
            password='OriginalPass123!',
        )
        original_password = existing.password

        response = self.client.post(
            reverse('accounts:register_student'),
            self.payload(),
        )

        self.assertContains(response, 'Ce nom d’utilisateur est déjà utilisé.')
        existing.refresh_from_db()
        self.assertEqual(existing.password, original_password)
        self.assertFalse(ClassroomMember.objects.filter(user=existing).exists())
        self.assertEqual(User.objects.filter(username__iexact='amina_2026').count(), 1)

    def test_pending_student_cannot_log_in_before_administrator_approval(self):
        self.client.post(
            reverse('accounts:register_student'),
            self.payload(),
        )
        response = self.client.post(
            reverse('accounts:login'),
            {'username': 'amina_2026', 'password': 'LongPass123!'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            'Votre demande d’inscription attend la validation de l’administrateur.',
        )
        self.assertNotIn('user_id', self.client.session)

    def test_only_staff_or_superuser_can_open_the_approval_dashboard(self):
        teacher = User.objects.create_user(
            username='legacy_teacher',
            email='legacy-teacher@example.test',
            password='TeacherPass123!',
            role='teacher',
        )
        self.login_with_session(teacher)
        response = self.client.get(reverse('accounts:admin_dashboard'))
        self.assertRedirects(
            response,
            reverse('education:home'),
            fetch_redirect_response=False,
        )

        administrator = User.objects.create_user(
            username='principal_admin',
            email='principal@example.test',
            password='AdminPass123!',
            role='teacher',
            is_staff=True,
            is_superuser=True,
        )
        self.login_with_session(administrator)
        response = self.client.get(reverse('accounts:admin_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Demandes d’inscription')

    def test_administrator_can_approve_a_pending_student(self):
        user = User.objects.create_user(
            username='pending_student',
            email=None,
            password='StudentPass123!',
            role='student',
            approval_status='pending',
            is_active=False,
        )
        StudentProfile.objects.create(user=user, niveau=self.classroom.niveau)
        ClassroomMember.objects.create(classroom=self.classroom, user=user)
        administrator = User.objects.create_user(
            username='approver',
            email='approver@example.test',
            password='AdminPass123!',
            role='teacher',
            is_staff=True,
            is_superuser=True,
        )
        self.login_with_session(administrator)

        response = self.client.post(
            reverse('accounts:review_registration', args=[user.pk]),
            {'action': 'approve'},
        )

        self.assertRedirects(response, reverse('accounts:admin_dashboard'))
        user.refresh_from_db()
        self.assertEqual(user.approval_status, 'approved')
        self.assertTrue(user.is_active)
        self.client.post(reverse('accounts:logout'))
        login_response = self.client.post(
            reverse('accounts:login'),
            {'username': user.username, 'password': 'StudentPass123!'},
        )
        self.assertEqual(login_response.status_code, 302)
        self.assertEqual(self.client.session.get('user_id'), user.pk)

    def test_administrator_can_reject_and_delete_only_the_pending_account(self):
        user = User.objects.create_user(
            username='rejected_student',
            email=None,
            password='StudentPass123!',
            role='student',
            approval_status='pending',
            is_active=False,
        )
        StudentProfile.objects.create(user=user, niveau=self.classroom.niveau)
        membership = ClassroomMember.objects.create(
            classroom=self.classroom,
            user=user,
        )
        administrator = User.objects.create_user(
            username='rejector',
            email='rejector@example.test',
            password='AdminPass123!',
            role='teacher',
            is_staff=True,
            is_superuser=True,
        )
        self.login_with_session(administrator)

        response = self.client.post(
            reverse('accounts:review_registration', args=[user.pk]),
            {'action': 'reject'},
        )

        self.assertRedirects(response, reverse('accounts:admin_dashboard'))
        self.assertFalse(User.objects.filter(pk=user.pk).exists())
        self.assertFalse(StudentProfile.objects.filter(user_id=user.pk).exists())
        self.assertFalse(ClassroomMember.objects.filter(pk=membership.pk).exists())
