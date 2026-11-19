"""Écran d'accueil mobile (/bienvenue/) : destination de « Commencer » selon la session."""
from django.test import TestCase
from django.urls import reverse

from accounts.models import User


class WelcomeScreenTests(TestCase):
    def login_as(self, **kwargs):
        user = User.objects.create_user(username=kwargs.pop('username'), **kwargs)
        session = self.client.session
        session['user_id'] = user.pk
        session.save()
        return user

    def start_href(self, response):
        html = response.content.decode()
        marker = 'class="welcome-start" href="'
        start = html.index(marker) + len(marker)
        return html[start:html.index('"', start)]

    def test_anonymous_goes_to_existing_login(self):
        response = self.client.get(reverse('education:welcome'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.start_href(response), reverse('accounts:login'))
        for text in ('Bienvenue sur EduBac', 'Apprendre • Réviser • Réussir', 'Commencer',
                     'EduBac, ensemble vers la réussite', 'Cours', 'Quiz', 'Messages', 'Suivi',
                     'name="robots" content="noindex"'):
            self.assertContains(response, text)

    def test_student_goes_to_dashboard(self):
        self.login_as(username='w-eleve', email='w-eleve@example.test', role='student')
        response = self.client.get(reverse('education:welcome'))
        self.assertEqual(self.start_href(response), reverse('accounts:dashboard'))
        self.assertContains(response, reverse('accounts:progress'))

    def test_teacher_goes_to_dashboard_with_teacher_links(self):
        self.login_as(username='w-prof', email='w-prof@example.test', role='teacher')
        response = self.client.get(reverse('education:welcome'))
        self.assertEqual(self.start_href(response), reverse('accounts:dashboard'))
        self.assertContains(response, reverse('quizzes:teacher_ai'))
        self.assertContains(response, reverse('quizzes:teacher_stats'))

    def test_administrator_goes_to_admin_dashboard(self):
        self.login_as(username='w-admin', email='w-admin@example.test', role='teacher', is_staff=True)
        response = self.client.get(reverse('education:welcome'))
        self.assertEqual(self.start_href(response), reverse('accounts:admin_dashboard'))

    def test_home_loads_the_mobile_gate_without_server_redirect(self):
        response = self.client.get(reverse('education:home'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'welcome-gate.js')
        self.assertContains(response, f'data-welcome-url="{reverse("education:welcome")}"')
