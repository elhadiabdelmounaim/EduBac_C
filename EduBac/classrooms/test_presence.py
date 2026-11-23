"""Présence des élèves : l'activité est notée (au plus une fois par minute) et seul
l'administrateur voit, dans une classe, qui est actif dans l'application."""
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import StudentProfile, User
from classrooms.models import Classroom, ClassroomMember


class PresenceTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='admin', email='a@x.test', role='teacher',
                                              is_staff=True, password='x')
        self.prof = User.objects.create_user(username='prof', email='p@x.test', role='teacher', password='x')
        self.classe = Classroom.objects.create(name='1BAC A', niveau='1ere_bac_sc', teacher=self.prof)
        self.eleves = {}
        for nom in ('amal', 'badr', 'chama'):
            u = User.objects.create_user(username=nom, email=f'{nom}@x.test', role='student',
                                         first_name=nom.capitalize(), password='x')
            StudentProfile.objects.create(user=u, niveau='1ere_bac_sc')
            ClassroomMember.objects.create(classroom=self.classe, user=u)
            self.eleves[nom] = u
        maintenant = timezone.now()
        User.objects.filter(pk=self.eleves['amal'].pk).update(derniere_activite=maintenant - timedelta(minutes=1))
        User.objects.filter(pk=self.eleves['badr'].pk).update(derniere_activite=maintenant - timedelta(hours=2))

    def connecter(self, user):
        session = self.client.session
        session['user_id'] = user.pk
        session['role'] = user.role
        session['password_session_version'] = user.password_session_version
        session.save()

    def test_activite_notee_au_plus_une_fois_par_minute(self):
        eleve = self.eleves['chama']
        self.connecter(eleve)
        self.client.get(reverse('accounts:dashboard'))
        eleve.refresh_from_db()
        premiere = eleve.derniere_activite
        self.assertIsNotNone(premiere)
        self.client.get(reverse('accounts:dashboard'))
        eleve.refresh_from_db()
        self.assertEqual(eleve.derniere_activite, premiere)        # moins d'une minute : pas de nouvelle écriture
        User.objects.filter(pk=eleve.pk).update(derniere_activite=premiere - timedelta(minutes=2))
        self.assertEqual(self.client.post(reverse('accounts:presence')).status_code, 204)
        eleve.refresh_from_db()
        self.assertGreater(eleve.derniere_activite, premiere - timedelta(minutes=1))

    def test_presence_anonyme_refusee(self):
        self.assertEqual(self.client.post(reverse('accounts:presence')).status_code, 401)
        self.assertEqual(self.client.get(reverse('accounts:presence')).status_code, 405)

    def test_admin_voit_les_actifs(self):
        self.connecter(self.admin)
        r = self.client.get(reverse('classrooms:detail', args=[self.classe.pk]))
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn('1 actif maintenant', html)
        self.assertEqual(html.count('data-presence="actif"'), 1)
        self.assertIn('Actif il y a 2', html)
        self.assertIn('Pas encore d’activité', html)
        # Les actifs d'abord, puis le plus récemment vu.
        ordre = [m.user.username for m in r.context['members']]
        self.assertEqual(ordre, ['amal', 'badr', 'chama'])
        self.assertContains(r, 'js/presence.js')

    def test_professeur_et_eleve_ne_voient_pas_la_presence(self):
        for user in (self.prof, self.eleves['badr']):
            self.connecter(user)
            r = self.client.get(reverse('classrooms:detail', args=[self.classe.pk]))
            self.assertEqual(r.status_code, 200)
            self.assertNotContains(r, 'data-presence')
            self.assertNotContains(r, 'actif maintenant')
