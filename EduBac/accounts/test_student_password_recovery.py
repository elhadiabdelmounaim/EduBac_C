from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from classrooms.models import Classroom, ClassroomMember
from education.models import Course, Lesson
from quizzes.models import Attempt, Quiz

from .models import (
    StudentPasswordResetEvent,
    StudentProfile,
    User,
)


@override_settings(
    ALLOWED_HOSTS=['testserver', 'localhost', '127.0.0.1'],
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
)
class StudentPasswordRecoveryTests(TestCase):
    def setUp(self):
        mail.get_connection()
        mail.outbox.clear()
        self.admin = User.objects.create_superuser(
            username='recovery_admin',
            email='recovery-admin@example.test',
            password='AdminStrongPass123!',
        )
        self.student = User.objects.create_user(
            username='salma.math',
            email='salma@example.test',
            password='StudentCurrentPass123!',
            first_name='Salma',
            last_name='Math',
            role='student',
            is_active=True,
            approval_status='approved',
        )
        self.profile = StudentProfile.objects.create(
            user=self.student,
            niveau='tronc_commun',
        )
        self.classroom = Classroom.objects.create(
            name='Tronc Commun A',
            niveau='tronc_commun',
        )
        self.membership = ClassroomMember.objects.create(
            user=self.student,
            classroom=self.classroom,
        )
        self.course = Course.objects.create(
            name='Mathématiques',
            niveau='tronc_commun',
            order=1,
        )
        self.lesson = Lesson.objects.create(
            course=self.course,
            order=1,
            title='Les nombres réels',
            content='Leçon de test',
        )
        self.quiz = Quiz.objects.create(
            title='Évaluation conservée',
            lesson=self.lesson,
        )
        self.attempt = Attempt.objects.create(
            student=self.student,
            quiz=self.quiz,
            submitted_at=timezone.now(),
            score=82.5,
        )
        self.admin_client = self.client
        admin_login = self.admin_client.post(
            reverse('accounts:login'),
            {
                'username': self.admin.username,
                'password': 'AdminStrongPass123!',
            },
        )
        self.assertRedirects(admin_login, reverse('accounts:teacher_portal'))
        mail.outbox.clear()

    def _confirm_url(self):
        return reverse(
            'accounts:confirm_student_password_reset',
            args=[self.student.pk],
        )

    def _reset_url(self):
        return reverse(
            'accounts:reset_student_password',
            args=[self.student.pk],
        )

    def test_login_explains_manual_recovery_without_email_link(self):
        response = self.client_class().get(reverse('accounts:login'))

        self.assertContains(response, 'Mot de passe oublié ?')
        self.assertContains(response, 'Contactez votre professeur')
        self.assertContains(response, 'Votre compte et vos résultats seront conservés.')
        self.assertNotContains(response, 'account_reset_password')
        self.assertEqual(
            len(mail.outbox),
            0,
            [message.subject for message in mail.outbox],
        )

    def test_superuser_searches_students_and_sees_account_details(self):
        for query in ('Salma', 'Math', 'salma.math'):
            with self.subTest(query=query):
                response = self.admin_client.get(
                    reverse('accounts:admin_dashboard'),
                    {'student_q': query},
                )
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'Salma Math')
                self.assertContains(response, 'salma.math')
                self.assertContains(response, 'Tronc Commun A')
                self.assertContains(response, 'Actif')
                self.assertContains(response, 'Réinitialiser le mot de passe')

    def test_student_and_staff_cannot_reset_passwords(self):
        student_client = self.client_class()
        student_client.post(
            reverse('accounts:login'),
            {'username': self.student.username, 'password': 'StudentCurrentPass123!'},
        )
        response = student_client.get(self._confirm_url())
        self.assertEqual(response.status_code, 403)

        staff = User.objects.create_user(
            username='staff_teacher',
            email='staff@example.test',
            password='TeacherStrongPass123!',
            role='teacher',
            is_staff=True,
        )
        staff_client = self.client_class()
        staff_client.post(
            reverse('accounts:login'),
            {'username': staff.username, 'password': 'TeacherStrongPass123!'},
        )
        response = staff_client.get(self._confirm_url())
        self.assertEqual(response.status_code, 403)

    def test_recovery_requires_identity_confirmation_and_a_single_use_nonce(self):
        confirmation = self.admin_client.get(self._confirm_url())
        nonce = confirmation.context['nonce']
        original_password_hash = self.student.password

        missing_identity = self.admin_client.post(
            self._reset_url(),
            {'nonce': nonce},
        )
        self.assertEqual(missing_identity.status_code, 200)
        self.assertContains(missing_identity, 'vérifié l’identité')
        self.student.refresh_from_db()
        self.assertEqual(self.student.password, original_password_hash)
        self.assertFalse(self.student.must_change_password)
        self.assertEqual(StudentPasswordResetEvent.objects.count(), 0)

        # The administrator's direct identity check is the recovery path; no
        # email verification or message is required for this reset.
        self.student.email_verified = False
        self.student.save(update_fields=['email_verified'])
        reset = self.admin_client.post(
            self._reset_url(),
            {'nonce': nonce, 'identity_verified': 'yes'},
        )

        self.assertEqual(reset.status_code, 200)
        self.assertIn('no-store', reset['Cache-Control'])
        temporary_password = reset.context['temporary_password']
        self.assertTrue(temporary_password)
        self.assertContains(reset, temporary_password)
        self.student.refresh_from_db()
        self.assertTrue(self.student.check_password(temporary_password))
        self.assertNotIn(temporary_password, self.student.password)
        self.assertTrue(self.student.must_change_password)
        self.assertEqual(self.student.password_session_version, 1)
        self.assertEqual(
            len(mail.outbox),
            0,
            [message.subject for message in mail.outbox],
        )

        event = StudentPasswordResetEvent.objects.get()
        self.assertEqual(event.student, self.student)
        self.assertEqual(event.administrator, self.admin)
        self.assertEqual(event.administrator_id_snapshot, self.admin.pk)
        self.assertEqual(event.administrator_username, self.admin.username)
        self.assertNotIn(temporary_password, str(event.__dict__))
        self.assertNotIn(temporary_password, str(dict(self.admin_client.session)))

        repeated_post = self.admin_client.post(
            self._reset_url(),
            {'nonce': nonce, 'identity_verified': 'yes'},
        )
        self.assertEqual(repeated_post.status_code, 302)
        self.assertEqual(StudentPasswordResetEvent.objects.count(), 1)

    def test_old_sessions_are_invalidated_after_reset(self):
        student_client = self.client_class()
        student_client.post(
            reverse('accounts:login'),
            {'username': self.student.username, 'password': 'StudentCurrentPass123!'},
        )
        old_session_key = student_client.session.session_key
        confirmation = self.admin_client.get(self._confirm_url())
        self.admin_client.post(
            self._reset_url(),
            {
                'nonce': confirmation.context['nonce'],
                'identity_verified': 'yes',
            },
        )

        response = student_client.get(reverse('accounts:profile'))

        self.assertRedirects(response, reverse('accounts:login'))
        self.assertNotEqual(student_client.session.session_key, old_session_key)
        self.assertNotIn('user_id', student_client.session)

    def test_temp_password_forces_secure_change_and_preserves_student_data(self):
        before_user_count = User.objects.count()
        confirmation = self.admin_client.get(self._confirm_url())
        reset = self.admin_client.post(
            self._reset_url(),
            {
                'nonce': confirmation.context['nonce'],
                'identity_verified': 'yes',
            },
        )
        temporary_password = reset.context['temporary_password']
        student_client = self.client_class()

        login_response = student_client.post(
            reverse('accounts:login'),
            {
                'username': self.student.username,
                'password': temporary_password,
            },
        )
        self.assertRedirects(login_response, reverse('accounts:change_password'))
        protected = student_client.get(reverse('accounts:profile'))
        self.assertRedirects(protected, reverse('accounts:change_password'))
        self.assertEqual(
            student_client.get(reverse('accounts:change_password')).status_code,
            200,
        )

        weak_password = student_client.post(
            reverse('accounts:change_password'),
            {
                'new_password1': '12345',
                'new_password2': '12345',
            },
        )
        self.assertEqual(weak_password.status_code, 200)
        self.assertTrue(weak_password.context['form'].errors)

        mismatch = student_client.post(
            reverse('accounts:change_password'),
            {
                'new_password1': 'NewStudentPass!2032',
                'new_password2': 'DifferentStudentPass!2032',
            },
        )
        self.assertEqual(mismatch.status_code, 200)
        self.assertTrue(mismatch.context['form'].errors)

        new_password = 'NewStudentPass!2032'
        changed = student_client.post(
            reverse('accounts:change_password'),
            {
                'new_password1': new_password,
                'new_password2': new_password,
            },
        )
        self.assertRedirects(changed, reverse('accounts:dashboard'), fetch_redirect_response=False)

        self.student.refresh_from_db()
        self.assertFalse(self.student.must_change_password)
        self.assertTrue(self.student.check_password(new_password))
        self.assertEqual(User.objects.count(), before_user_count)
        self.assertEqual(StudentProfile.objects.get(pk=self.profile.pk).user_id, self.student.pk)
        self.assertTrue(ClassroomMember.objects.filter(pk=self.membership.pk).exists())
        self.assertEqual(Attempt.objects.get(pk=self.attempt.pk).score, 82.5)

        profile_response = student_client.get(reverse('accounts:profile'))
        self.assertEqual(profile_response.status_code, 200)
        student_client.get(reverse('accounts:logout'))
        normal_login = student_client.post(
            reverse('accounts:login'),
            {'username': self.student.username, 'password': new_password},
        )
        self.assertRedirects(
            normal_login,
            reverse('accounts:dashboard'),
            fetch_redirect_response=False,
        )
