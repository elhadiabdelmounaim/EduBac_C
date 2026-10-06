from django.test import TestCase, Client, override_settings
from accounts.models import User, StudentProfile, TeacherProfile


@override_settings(ALLOWED_HOSTS=['testserver', 'localhost', '127.0.0.1'])
class SimpleSessionAuthTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.student = User(username='s1', email='s1@test.com', role='student')
        self.student.set_password('pass123')
        self.student.save()
        StudentProfile.objects.create(user=self.student, niveau='tronc_commun')
        self.teacher = User(username='t1', email='t1@test.com', role='teacher')
        self.teacher.set_password('pass123')
        self.teacher.save()
        TeacherProfile.objects.create(user=self.teacher)

    def _login(self, username, password='pass123'):
        return self.client.post('/compte/connexion/', {
            'username': username, 'password': password,
        })

    def test_login_success_sets_session(self):
        r = self._login('s1')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.client.session.get('user_id'), self.student.id)

    def test_login_wrong_password(self):
        r = self._login('s1', 'bad')
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(self.client.session.get('user_id'))

    def test_login_password_toggle_has_single_accessible_toggle_handler(self):
        response = self.client.get('/compte/connexion/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'aria-label="Afficher le mot de passe"')
        self.assertContains(response, 'aria-pressed="false"')
        self.assertContains(response, '/static/js/edubac-ui.js')
        # The page-specific click listener used to cancel out the global toggle.
        self.assertNotContains(response, "document.querySelectorAll('.password-toggle')")

    def test_logout_clears_session(self):
        self._login('s1')
        self.client.get('/compte/deconnexion/')
        self.assertIsNone(self.client.session.get('user_id'))

    def test_student_blocked_from_teacher_page(self):
        self._login('s1')
        r = self.client.get('/quizzes/gestion/')
        self.assertEqual(r.status_code, 302)

    def test_teacher_manage_ok(self):
        self._login('t1')
        r = self.client.get('/quizzes/gestion/')
        self.assertEqual(r.status_code, 200)


@override_settings(ALLOWED_HOSTS=['testserver', 'localhost', '127.0.0.1'])
class SearchAndExportSmokeTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.teacher = User(username='tsearch', email='ts@test.com', role='teacher')
        self.teacher.set_password('pass123')
        self.teacher.save()
        TeacherProfile.objects.create(user=self.teacher)

    def test_search_page(self):
        r = self.client.get('/recherche/?q=math')
        self.assertEqual(r.status_code, 200)

    def test_export_requires_teacher(self):
        r = self.client.get('/quizzes/export-resultats/')
        self.assertIn(r.status_code, (302, 403))
        self.client.post('/compte/connexion/', {'username': 'tsearch', 'password': 'pass123'})
        r = self.client.get('/quizzes/export-resultats/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('text/csv', r['Content-Type'])

    def test_student_cannot_export_results(self):
        student = User.objects.create_user(
            username='export_student', email='export_student@example.test', role='student',
        )
        session = self.client.session
        session['user_id'] = student.pk
        session.save()
        response = self.client.get('/quizzes/export-resultats/')
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('Content-Disposition', response)
