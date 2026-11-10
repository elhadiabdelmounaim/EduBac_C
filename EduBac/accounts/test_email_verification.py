import re
import time
from unittest.mock import patch

from django.core import mail
from django.core.cache import cache
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse

from .models import StudentProfile, TeacherProfile, User


@override_settings(
    ALLOWED_HOSTS=['testserver', 'localhost', '127.0.0.1'],
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
)
class EmailVerificationTests(TestCase):
    def setUp(self):
        self.client = Client()
        cache.clear()
        mail.outbox.clear()

    def register(self, role='student', email='amina@example.test'):
        url_name = (
            'accounts:register_teacher'
            if role == 'teacher'
            else 'accounts:register_student'
        )
        data = {
            'name': 'Amina El Amrani',
            'email': email,
            'password': 'LongPass123!',
            'password2': 'LongPass123!',
        }
        if role == 'student':
            data['niveau'] = 'tronc_commun'
        return self.client.post(reverse(url_name), data)

    def verification_path(self, message=None):
        body = message or mail.outbox[-1].body
        match = re.search(
            r'/compte/verification-email/confirmer/([^\s]+)',
            body,
        )
        self.assertIsNotNone(match, 'Le message doit contenir un lien de vérification.')
        token = match.group(1).rstrip('/')
        return reverse('accounts:confirm_email', kwargs={'token': token})

    def test_student_and_teacher_registration_send_links_without_logging_in(self):
        for role, email, profile_model in (
            ('student', 'student@example.test', StudentProfile),
            ('teacher', 'teacher@example.test', TeacherProfile),
        ):
            with self.subTest(role=role):
                cache.clear()
                mail.outbox.clear()
                response = self.register(role=role, email=email)
                self.assertRedirects(
                    response,
                    reverse('accounts:email_verification_pending'),
                    fetch_redirect_response=False,
                )
                user = User.objects.get(email=email)
                self.assertFalse(user.email_verified)
                self.assertTrue(profile_model.objects.filter(user=user).exists())
                self.assertNotIn('user_id', self.client.session)
                self.assertEqual(len(mail.outbox), 1)
                self.assertIn(email, mail.outbox[0].to)
                self.assertIn('Vérifie ton adresse e-mail', mail.outbox[0].subject)

    def test_verification_link_confirms_email_and_then_login_succeeds(self):
        self.register(email='verified@example.test')
        user = User.objects.get(email='verified@example.test')
        response = self.client.get(self.verification_path())
        self.assertEqual(response.status_code, 200)
        user.refresh_from_db()
        self.assertTrue(user.email_verified)
        self.assertContains(response, 'Adresse e-mail vérifiée')

        self.client.post(reverse('accounts:logout'))
        login_response = self.client.post(
            reverse('accounts:login'),
            {'email': user.email, 'password': 'LongPass123!'},
        )
        self.assertEqual(login_response.status_code, 302)
        self.assertEqual(
            self.client.session.get('user_id'),
            user.pk,
        )

    def test_correct_password_cannot_log_in_before_verification(self):
        user = User.objects.create_user(
            username='unverified',
            email='unverified@example.test',
            password='LongPass123!',
            email_verified=False,
        )
        response = self.client.post(
            reverse('accounts:login'),
            {'email': user.email, 'password': 'LongPass123!'},
        )
        self.assertRedirects(
            response,
            reverse('accounts:email_verification_pending'),
            fetch_redirect_response=False,
        )
        self.assertNotIn('user_id', self.client.session)

    def test_middleware_clears_a_session_for_an_unverified_account(self):
        user = User.objects.create_user(
            username='unverified_session',
            email='unverified-session@example.test',
            password='LongPass123!',
            email_verified=False,
        )
        session = self.client.session
        session['user_id'] = user.pk
        session['role'] = user.role
        session.save()

        response = self.client.get(reverse('accounts:profile'))
        self.assertRedirects(
            response,
            reverse('accounts:login'),
            fetch_redirect_response=False,
        )
        self.assertNotIn('user_id', self.client.session)

    def test_existing_accounts_remain_verified_and_can_log_in(self):
        user = User.objects.create_user(
            username='existing_legacy_account',
            email='existing-legacy@example.test',
            password='LongPass123!',
        )
        self.assertTrue(user.email_verified)
        response = self.client.post(
            reverse('accounts:login'),
            {'email': user.email, 'password': 'LongPass123!'},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.session.get('user_id'), user.pk)

    def test_expired_link_does_not_verify_the_account(self):
        user = User.objects.create_user(
            username='expired',
            email='expired@example.test',
            password='LongPass123!',
            email_verified=False,
        )
        with override_settings(EMAIL_VERIFICATION_TOKEN_MAX_AGE=1):
            from accounts.email_verification import send_verification_email

            self.assertEqual(send_verification_email(self._request(), user), 'sent')
            path = self.verification_path()
            time.sleep(2.1)
            response = self.client.get(path)
        user.refresh_from_db()
        self.assertFalse(user.email_verified)
        self.assertContains(response, 'Le lien a expiré')

    def test_resend_is_available_and_obeys_the_email_cooldown(self):
        user = User.objects.create_user(
            username='resend',
            email='resend@example.test',
            password='LongPass123!',
            email_verified=False,
        )
        url = reverse('accounts:resend_verification')
        response = self.client.post(url, {'email': user.email}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Si cette adresse correspond à un compte non vérifié', response.content.decode())

        response = self.client.post(url, {'email': user.email}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertContains(
            response,
            'un nouveau lien a été envoyé si la demande est autorisée',
        )

    def test_resend_logs_safe_stages_without_email_or_token(self):
        email = 'safe-log-resend@example.test'
        user = User.objects.create_user(
            username='safe_log_resend',
            email=email,
            password='LongPass123!',
            email_verified=False,
        )

        with (
            self.assertLogs('accounts.views', level='INFO') as view_logs,
            self.assertLogs(
                'accounts.email_verification',
                level='INFO',
            ) as service_logs,
        ):
            response = self.client.post(
                reverse('accounts:resend_verification'),
                {'email': user.email},
                follow=True,
            )

        diagnostics = '\n'.join(view_logs.output + service_logs.output)
        self.assertEqual(response.status_code, 200)
        self.assertIn('stage=user_lookup outcome=eligible', diagnostics)
        self.assertIn('stage=send_service outcome=sent', diagnostics)
        self.assertIn(
            'stage=django_mail_send outcome=backend_returned_one',
            diagnostics,
        )
        self.assertNotIn(email, diagnostics)
        self.assertNotIn(self.verification_path().split('/')[-2], diagnostics)
        self.assertContains(
            response,
            'Si cette adresse correspond à un compte non vérifié',
        )

    @patch(
        'accounts.email_verification.EmailMultiAlternatives.send',
        side_effect=OSError('private diagnostic detail'),
    )
    def test_resend_failure_logs_stage_and_type_without_private_details(self, _send):
        email = 'safe-log-failure@example.test'
        User.objects.create_user(
            username='safe_log_failure',
            email=email,
            password='LongPass123!',
            email_verified=False,
        )

        with self.assertLogs(
            'accounts.email_verification',
            level='ERROR',
        ) as service_logs:
            response = self.client.post(
                reverse('accounts:resend_verification'),
                {'email': email},
                follow=True,
            )

        diagnostics = '\n'.join(service_logs.output)
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            'stage=django_mail_send outcome=failed exception_type=OSError',
            diagnostics,
        )
        self.assertNotIn(email, diagnostics)
        self.assertNotIn('private diagnostic detail', diagnostics)
        self.assertContains(
            response,
            'Si cette adresse correspond à un compte non vérifié',
        )

    @override_settings(EMAIL_VERIFICATION_RESEND_COOLDOWN=0)
    def test_resend_can_send_again_after_cooldown(self):
        user = User.objects.create_user(
            username='resend_again',
            email='resend-again@example.test',
            password='LongPass123!',
            email_verified=False,
        )
        url = reverse('accounts:resend_verification')
        self.client.post(url, {'email': user.email})
        self.client.post(url, {'email': user.email})
        self.assertEqual(len(mail.outbox), 2)

    def test_invalid_email_is_rejected_without_creating_an_account(self):
        response = self.register(email='not-an-email')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Saisis une adresse e-mail valide')
        self.assertFalse(User.objects.filter(email='not-an-email').exists())

    @patch(
        'accounts.email_verification.EmailMultiAlternatives.send',
        side_effect=OSError('SMTP is unavailable'),
    )
    def test_smtp_failure_keeps_the_account_pending_and_allows_retry(self, _send):
        with self.assertLogs('accounts.email_verification', level='ERROR'):
            response = self.register(email='mail-failure@example.test')
        self.assertEqual(response.status_code, 302)
        pending = self.client.get(response['Location'])
        user = User.objects.get(email='mail-failure@example.test')
        self.assertEqual(pending.status_code, 200)
        self.assertContains(pending, 'le message n’a pas pu être envoyé')
        self.assertFalse(user.email_verified)
        self.assertNotIn('user_id', self.client.session)

    @override_settings(
        EMAIL_VERIFICATION_RESEND_COOLDOWN=0,
        EMAIL_VERIFICATION_IP_HOURLY_LIMIT=1,
    )
    def test_resend_is_limited_per_ip(self):
        first = User.objects.create_user(
            username='first_ip_limit',
            email='first-ip-limit@example.test',
            password='LongPass123!',
            email_verified=False,
        )
        User.objects.create_user(
            username='second_ip_limit',
            email='second-ip-limit@example.test',
            password='LongPass123!',
            email_verified=False,
        )
        url = reverse('accounts:resend_verification')
        self.client.post(url, {'email': first.email})
        response = self.client.post(
            url,
            {'email': 'second-ip-limit@example.test'},
            follow=True,
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertContains(
            response,
            'un nouveau lien a été envoyé si la demande est autorisée',
        )

    def test_unknown_and_verified_addresses_do_not_receive_resend_mail(self):
        verified = User.objects.create_user(
            username='already_verified',
            email='already-verified@example.test',
            password='LongPass123!',
        )
        url = reverse('accounts:resend_verification')
        for email in ('unknown@example.test', verified.email):
            response = self.client.post(url, {'email': email}, follow=True)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'Si cette adresse correspond à un compte non vérifié')
        self.assertEqual(len(mail.outbox), 0)

    def _request(self):
        return RequestFactory().get('/')
