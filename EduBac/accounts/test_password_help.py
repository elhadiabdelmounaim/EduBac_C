"""« Mot de passe oublié » sans e-mail : demande depuis la connexion, traitement par l'administrateur."""
import re

from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse

from notifications.models import Notification

from .models import PasswordHelpRequest, User

FORGOT = reverse('accounts:forgot_password')
SENT = FORGOT + '?envoye=1'


class PasswordHelpRequestTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_superuser(
            username='prof-admin', email='prof-admin@example.test', password='AdminStrongPass123!')
        self.student = User.objects.create_user(
            username='salma.b', email='salma.b@example.test', password='AncienMotDePasse123!',
            first_name='Salma', last_name='Bennani', role='student')
        self.admin_client = Client()
        self.login(self.admin_client, self.admin)

    def login(self, client, user):
        session = client.session
        session['user_id'] = user.pk
        session.save()

    def ask(self, name, classroom='', **extra):
        return self.client.post(FORGOT, {'name': name, 'classroom': classroom, **extra})

    def test_login_page_links_to_the_request_form(self):
        self.assertContains(self.client.get(reverse('accounts:login')), FORGOT)
        page = self.client.get(FORGOT)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'Aucun e-mail n’est nécessaire')

    def test_request_is_recorded_matched_and_the_admin_is_notified(self):
        response = self.ask('  salma   BENNANI ', '1bac1')
        self.assertRedirects(response, SENT)
        help_request = PasswordHelpRequest.objects.get()
        self.assertEqual(help_request.name, 'salma BENNANI')
        self.assertEqual(help_request.classroom_hint, '1bac1')
        self.assertEqual(help_request.student, self.student)
        note = Notification.objects.get(recipient=self.admin)
        self.assertIn('salma BENNANI (1bac1)', note.message)
        self.assertIn('#password-requests', note.link)
        self.assertContains(self.client.get(SENT), 'Demande envoyée')

    def test_unknown_name_gets_the_same_answer_without_revealing_accounts(self):
        response = self.ask('Personne Inconnue')
        self.assertRedirects(response, SENT)
        self.assertIsNone(PasswordHelpRequest.objects.get().student)

    def test_ambiguous_name_is_not_linked(self):
        User.objects.create_user(username='salma2', email='s2@example.test', role='student',
                                 first_name='Salma', last_name='Bennani')
        self.ask('Salma Bennani')
        self.assertIsNone(PasswordHelpRequest.objects.get().student)

    def test_validation_honeypot_duplicates_and_rate_limit(self):
        self.assertContains(self.ask('ab'), 'Indiquez votre nom')
        self.assertRedirects(self.ask('Robot Name', website='http://spam'), SENT)
        self.assertEqual(PasswordHelpRequest.objects.count(), 0)
        self.ask('Salma Bennani')
        self.ask('salma bennani')
        self.assertEqual(PasswordHelpRequest.objects.count(), 1)
        for i in range(3):
            self.ask(f'Élève numéro {i}')
        blocked = self.ask('Encore une demande')
        self.assertContains(blocked, 'Trop de demandes')
        self.assertEqual(PasswordHelpRequest.objects.count(), 4)

    def test_logged_in_user_is_sent_to_dashboard(self):
        self.login(self.client, self.student)
        self.assertRedirects(self.client.get(FORGOT), reverse('accounts:dashboard'),
                             fetch_redirect_response=False)

    def test_admin_resets_from_the_request_and_student_must_choose_a_new_password(self):
        self.ask('Salma Bennani')
        help_request = PasswordHelpRequest.objects.get()
        dashboard = self.admin_client.get(reverse('accounts:admin_dashboard'))
        confirm_url = reverse('accounts:confirm_student_password_reset', args=[self.student.pk])
        self.assertContains(dashboard, f'{confirm_url}?demande={help_request.pk}')

        confirm = self.admin_client.get(f'{confirm_url}?demande={help_request.pk}')
        self.assertContains(confirm, f'name="help_request" value="{help_request.pk}"')
        reset = self.admin_client.post(
            reverse('accounts:reset_student_password', args=[self.student.pk]),
            {'nonce': confirm.context['nonce'], 'identity_verified': 'yes', 'help_request': help_request.pk})
        password = reset.context['temporary_password']
        self.assertRegex(password, r'^[a-hj-km-np-z2-9]{5}-[a-hj-km-np-z2-9]{5}$')

        help_request.refresh_from_db()
        self.assertEqual(help_request.status, PasswordHelpRequest.STATUS_DONE)
        self.assertEqual(help_request.handled_by, self.admin)
        self.assertContains(self.admin_client.get(reverse('accounts:admin_dashboard')),
                            'Aucune demande de mot de passe en attente')

        login = Client().post(reverse('accounts:login'), {'username': 'salma.b', 'password': password},
                              follow=True)
        self.assertEqual(login.resolver_match.url_name, 'change_password')

    def test_unrecognised_request_is_resolved_through_search(self):
        # « Salma B. » est désormais reconnu (identifiant salma.b) : nom vraiment inconnu ici.
        self.ask('S. Bennani-Alaoui', '1bac1')
        help_request = PasswordHelpRequest.objects.get()
        self.assertIsNone(help_request.student)
        dashboard = self.admin_client.get(reverse('accounts:admin_dashboard'))
        self.assertContains(dashboard, 'Rechercher l’élève')
        search = self.admin_client.get(reverse('accounts:admin_dashboard'),
                                       {'student_q': 'salma benn', 'demande': help_request.pk})
        self.assertEqual(search.context['student_results'], [self.student])
        confirm_url = reverse('accounts:confirm_student_password_reset', args=[self.student.pk])
        self.assertContains(search, f'{confirm_url}?demande={help_request.pk}')
        confirm = self.admin_client.get(f'{confirm_url}?demande={help_request.pk}')
        self.admin_client.post(
            reverse('accounts:reset_student_password', args=[self.student.pk]),
            {'nonce': confirm.context['nonce'], 'identity_verified': 'yes', 'help_request': help_request.pk})
        help_request.refresh_from_db()
        self.assertEqual(help_request.status, PasswordHelpRequest.STATUS_DONE)
        self.assertEqual(help_request.student, self.student)

    def test_dismiss_is_reserved_to_the_superuser(self):
        self.ask('Quelqu’un Dautre')
        help_request = PasswordHelpRequest.objects.get()
        url = reverse('accounts:dismiss_password_request', args=[help_request.pk])
        staff = User.objects.create_user(username='staff', email='staff@example.test',
                                         role='teacher', is_staff=True)
        other = Client()
        self.login(other, staff)
        other.post(url)
        self.assertNotContains(other.get(reverse('accounts:admin_dashboard')), 'Quelqu’un Dautre')
        help_request.refresh_from_db()
        self.assertEqual(help_request.status, PasswordHelpRequest.STATUS_PENDING)
        self.admin_client.post(url)
        help_request.refresh_from_db()
        self.assertEqual(help_request.status, PasswordHelpRequest.STATUS_DISMISSED)
