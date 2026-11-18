from django.test import TestCase
from django.urls import reverse

from accounts.models import User


class SystemStatusTests(TestCase):
    def test_admin_sees_checks_and_others_are_refused(self):
        student = User.objects.create(username='omar', email='o@t.test')
        session = self.client.session
        session['user_id'] = student.pk
        session.save()
        self.assertNotEqual(self.client.get(reverse('accounts:system_status')).status_code, 200)
        admin = User.objects.create(username='prof', email='p@t.test', role='teacher', is_superuser=True, is_staff=True)
        session = self.client.session
        session['user_id'] = admin.pk
        session.save()
        page = self.client.get(reverse('accounts:system_status'))
        self.assertEqual(page.status_code, 200)
        for label in ('Base de données', 'Sauvegarde', 'E-mails', 'Notifications du téléphone', 'Pages légales'):
            self.assertContains(page, label)
        self.assertNotContains(page, 'PASSWORD=')
