from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import User


class StaleCsrfTokenTests(TestCase):
    """Un formulaire de connexion périmé ne doit pas aboutir à une page 403 brute."""

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        User.objects.create_user(username='eleve', password='LongPass123!', email='e@example.test')

    def test_login_and_signup_pages_are_never_cached(self):
        for name in ('login', 'login_teacher', 'register_student'):
            response = self.client.get(reverse(f'accounts:{name}'))
            self.assertIn('no-cache', response['Cache-Control'], name)
            self.assertIn('csrftoken', response.cookies, name)

    def test_stale_token_on_login_shows_a_fresh_form_with_a_message(self):
        self.client.get(reverse('accounts:login'))
        response = self.client.post(
            reverse('accounts:login'),
            {'username': 'eleve', 'password': 'LongPass123!', 'csrfmiddlewaretoken': 'x' * 64},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertRedirects(response, reverse('accounts:login'))
        self.assertContains(response, 'La page avait expiré')
        self.assertNotIn('user_id', self.client.session, 'rien n’est traité avec un jeton invalide')

    def test_stale_token_elsewhere_is_still_refused(self):
        self.client.get(reverse('accounts:login'))
        response = self.client.post(reverse('notifications:mark_all_read'), {'csrfmiddlewaretoken': 'x' * 64})
        self.assertEqual(response.status_code, 403)
