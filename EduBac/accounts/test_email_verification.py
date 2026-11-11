import re
import time
from datetime import datetime, timedelta, timezone as datetime_timezone
from unittest.mock import patch

from django.core import mail
from django.core.cache import cache
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse

from .models import User


@override_settings(
    ALLOWED_HOSTS=['testserver', 'localhost', '127.0.0.1'],
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
)
class EmailVerificationTests(TestCase):
    def setUp(self):
        self.client = Client()
        cache.clear()
        mail.outbox.clear()

    def verification_path(self, message=None):
        body = message or mail.outbox[-1].body
        match = re.search(
            r'/compte/verification-email/confirmer/([^\s]+)',
            body,
        )
        self.assertIsNotNone(match, 'Le message doit contenir un lien de vérification.')
        token = match.group(1).rstrip('/')
        return reverse('accounts:confirm_email', kwargs={'token': token})

    def test_verification_link_confirms_email_and_then_login_succeeds(self):
        user = User.objects.create_user(
            username='legacy_verified_email',
            email='verified@example.test',
            password='LongPass123!',
            email_verified=False,
        )
        from .email_verification import send_verification_email

        self.assertEqual(send_verification_email(self._request(), user), 'sent')
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
        response = self.client.post(
            url,
            {'email': user.email},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(
            'Si cette adresse correspond à un compte non vérifié',
            response.content.decode(),
        )

        with self.assertLogs(
            'accounts.email_verification',
            level='INFO',
        ) as throttle_logs:
            response = self.client.post(
                url,
                {'email': user.email},
                follow=True,
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertContains(
            response,
            'un nouveau lien a été envoyé si la demande est autorisée',
        )
        self.assertIn(
            'reason=email_cooldown remaining_seconds=',
            '\n'.join(throttle_logs.output),
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

    @override_settings(EMAIL_VERIFICATION_RESEND_COOLDOWN=60)
    @patch('accounts.email_verification.timezone.now')
    def test_resend_is_allowed_as_soon_as_cooldown_expires(self, mock_now):
        user = User.objects.create_user(
            username='resend_after_expiry',
            email='resend-after-expiry@example.test',
            password='LongPass123!',
            email_verified=False,
        )
        url = reverse('accounts:resend_verification')
        current_time = datetime(
            2026,
            11,
            10,
            12,
            0,
            tzinfo=datetime_timezone.utc,
        )
        mock_now.return_value = current_time

        first_response = self.client.post(url, {'email': user.email})
        mock_now.return_value = current_time + timedelta(seconds=61)
        second_response = self.client.post(url, {'email': user.email})

        self.assertEqual(first_response.status_code, 302)
        self.assertEqual(second_response.status_code, 302)
        self.assertEqual(len(mail.outbox), 2)

    def test_successful_email_starts_the_configured_email_cooldown(self):
        user = User.objects.create_user(
            username='smtp_acceptance_cooldown',
            email='smtp-accepted@example.test',
            password='LongPass123!',
            email_verified=False,
        )
        url = reverse('accounts:resend_verification')

        with (
            override_settings(
                EMAIL_VERIFICATION_RESEND_COOLDOWN=60,
            ),
            patch(
                'accounts.email_verification.EmailMultiAlternatives.send',
                return_value=1,
            ) as email_send,
        ):
            first_response = self.client.post(url, {'email': user.email})
            with self.assertLogs(
                'accounts.email_verification',
                level='INFO',
            ) as throttle_logs:
                second_response = self.client.post(url, {'email': user.email})

        self.assertEqual(first_response.status_code, 302)
        self.assertEqual(second_response.status_code, 302)
        self.assertEqual(email_send.call_count, 1)
        self.assertIn(
            'reason=email_cooldown remaining_seconds=',
            '\n'.join(throttle_logs.output),
        )

    def test_smtp_rejection_does_not_start_email_cooldown(self):
        user = User.objects.create_user(
            username='smtp_rejection_retry',
            email='smtp-retry@example.test',
            password='LongPass123!',
            email_verified=False,
        )
        url = reverse('accounts:resend_verification')

        with (
            override_settings(
                EMAIL_VERIFICATION_RESEND_COOLDOWN=60,
            ),
            patch(
                'accounts.email_verification.EmailMultiAlternatives.send',
                side_effect=[RuntimeError('private SMTP response'), 1],
            ) as email_send,
        ):
            failed_response = self.client.post(url, {'email': user.email})
            retry_response = self.client.post(url, {'email': user.email})

        self.assertEqual(failed_response.status_code, 302)
        self.assertEqual(retry_response.status_code, 302)
        self.assertEqual(email_send.call_count, 2)

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
