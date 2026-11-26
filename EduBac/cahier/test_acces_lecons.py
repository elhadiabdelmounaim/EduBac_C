"""Accès des élèves aux leçons : verrouillées tant qu'elles ne sont pas traitées, ouvertes
automatiquement par le cahier de textes ou par le professeur ; fichiers protégés côté serveur."""
import json
import shutil
import tempfile
from pathlib import Path

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from classrooms.models import Classroom, ClassroomMember
from education.models import Course, Lesson
from notifications.models import Notification

from .acces import cles_du_plan, lecons_ouvertes
from .models import AccesLecon

PDF = b'%PDF-1.4\n%test\n'


@override_settings(EMAIL_NOTIFICATIONS_ENABLED=False)
class AccesLeconsTests(TestCase):
    def setUp(self):
        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=media)
        override.enable()
        self.addCleanup(override.disable)
        self.prof = User.objects.create_user(username='prof', email='p@x.test', role='teacher')
        self.autre_prof = User.objects.create_user(username='prof2', email='p2@x.test', role='teacher')
        self.eleve = User.objects.create_user(username='amal', email='a@x.test', role='student', first_name='Amal')
        self.sans_classe = User.objects.create_user(username='zed', email='z@x.test', role='student')
        course = Course.objects.create(name='Mathématiques', niveau='1ere_bac_sc')
        # Leçon 4 de 1BAC SE : cours en ligne (plan) disponible dans le dépôt.
        self.lecon = Lesson.objects.create(course=course, title='Le produit scalaire dans le plan', order=4, content='')
        self.lecon2 = Lesson.objects.create(course=course, title='Une autre leçon', order=5, content='')
        self.classe = Classroom.objects.create(name='1BAC A', niveau='1ere_bac_sc', teacher=self.prof)
        ClassroomMember.objects.create(classroom=self.classe, user=self.eleve)
        # Un PDF de leçon (bouton « Télécharger »).
        dossier = Path(media) / 'lessons' / 'pdfs'
        dossier.mkdir(parents=True)
        (dossier / 'ps.pdf').write_bytes(PDF)
        self.lecon.pdf.name = 'lessons/pdfs/ps.pdf'
        self.lecon.save()

    def connecter(self, user):
        session = self.client.session
        session['user_id'] = user.pk
        session['role'] = user.role
        session['password_session_version'] = user.password_session_version
        session.save()

    def adresses(self, lecon=None):
        lecon = lecon or self.lecon
        return [
            reverse('education:lesson_detail', args=[lecon.pk]),
            reverse('education:lesson_pdf', args=[lecon.pk]),
            reverse('education:lesson_pdf', args=[lecon.pk]) + '?download=1',
            reverse('education:lesson_course_html', args=[lecon.pk]),
        ]

    def assert_verrouillee(self, user=None):
        if user:
            self.connecter(user)
        else:
            self.client.logout()
        for url in self.adresses():
            with self.subTest(url=url):
                r = self.client.get(url)
                self.assertEqual(r.status_code, 403)
                self.assertContains(r, 'Disponible après la séance', status_code=403)

    def test_eleve_et_visiteur_verrouilles_par_defaut(self):
        self.assert_verrouillee(self.eleve)
        self.assert_verrouillee(None)
        self.assert_verrouillee(self.sans_classe)

    def test_professeur_voit_tout(self):
        self.connecter(self.autre_prof)
        r = self.client.get(reverse('education:lesson_pdf', args=[self.lecon.pk]) + '?download=1')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(b''.join(r.streaming_content), PDF)
        self.assertEqual(self.client.get(self.adresses()[0]).status_code, 200)

    def test_ouverture_manuelle_puis_verrouillage(self):
        self.connecter(self.prof)
        r = self.client.post(reverse('cahier:acces', args=[self.classe.pk]), {'lecon': self.lecon.pk, 'action': 'ouvrir'})
        self.assertEqual(r.status_code, 302)
        self.connecter(self.eleve)
        r = self.client.get(reverse('education:lesson_pdf', args=[self.lecon.pk]) + '?download=1')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.get(self.adresses()[0]).status_code, 200)
        self.assertEqual(self.client.get(self.adresses(self.lecon2)[0]).status_code, 403)   # l'autre leçon reste fermée
        # Notification à la première ouverture.
        self.assertTrue(Notification.objects.filter(recipient=self.eleve, title='Nouveau cours disponible').exists())
        self.connecter(self.prof)
        self.client.post(reverse('cahier:acces', args=[self.classe.pk]), {'lecon': self.lecon.pk, 'action': 'fermer'})
        self.assert_verrouillee(self.eleve)
        # Rouvrir ne renvoie pas une deuxième notification.
        self.connecter(self.prof)
        self.client.post(reverse('cahier:acces', args=[self.classe.pk]), {'lecon': self.lecon.pk, 'action': 'ouvrir'})
        self.assertEqual(Notification.objects.filter(recipient=self.eleve, title='Nouveau cours disponible').count(), 1)

    def enregistrer(self, cles, jour):
        return self.client.post(reverse('cahier:enregistrer', args=[self.lecon.pk]), data=json.dumps(
            {'classe': self.classe.pk, 'date': jour, 'cles': cles}), content_type='application/json')

    def test_ouverture_automatique_par_le_cahier(self):
        cles = sorted(cles_du_plan(self.lecon))
        self.assertGreater(len(cles), 3)
        self.connecter(self.prof)
        moitie = len(cles) // 2
        self.assertEqual(self.enregistrer(cles[:moitie], '2026-11-02').status_code, 200)
        self.assertEqual(lecons_ouvertes(self.eleve), frozenset())          # plan incomplet : fermée
        self.assertEqual(self.enregistrer(cles[moitie:], '2026-11-04').status_code, 200)
        self.assertEqual(lecons_ouvertes(self.eleve), frozenset({self.lecon.pk}))
        # Supprimer une séance : le plan n'est plus couvert, la leçon se referme.
        from .models import Seance
        seance = Seance.objects.get(date='2026-11-04')
        self.client.post(reverse('cahier:supprimer', args=[seance.pk]))
        self.assertEqual(lecons_ouvertes(self.eleve), frozenset())
        # Le choix du professeur l'emporte sur le cahier.
        self.client.post(reverse('cahier:acces', args=[self.classe.pk]), {'lecon': self.lecon.pk, 'action': 'ouvrir'})
        self.assertEqual(lecons_ouvertes(self.eleve), frozenset({self.lecon.pk}))

    def test_ouvrir_jusqua_et_droits(self):
        self.connecter(self.autre_prof)
        r = self.client.post(reverse('cahier:acces', args=[self.classe.pk]), {'lecon': self.lecon2.pk, 'action': 'jusqua'})
        self.assertEqual(r.status_code, 404)                     # pas sa classe
        self.connecter(self.prof)
        self.client.post(reverse('cahier:acces', args=[self.classe.pk]), {'lecon': self.lecon2.pk, 'action': 'jusqua'})
        self.assertEqual(lecons_ouvertes(self.eleve), frozenset({self.lecon.pk, self.lecon2.pk}))
        page = self.client.get(reverse('cahier:acces', args=[self.classe.pk]))
        self.assertContains(page, 'Ouverte aux élèves')
        self.connecter(self.eleve)
        self.assertEqual(self.client.get(reverse('cahier:acces', args=[self.classe.pk])).status_code, 302)

    def test_listes_affichent_le_cadenas(self):
        AccesLecon.objects.create(classroom=self.classe, lesson=self.lecon2, decision=AccesLecon.OUVERT)
        self.connecter(self.eleve)
        page = self.client.get(reverse('education:niveau_detail', args=['1ere_bac_sc'])).content.decode()
        # Toutes les leçons du niveau (programme chargé par la page) sauf celle qui est ouverte.
        total = Lesson.objects.filter(course__niveau='1ere_bac_sc').count()
        self.assertEqual(page.count('data-verrou'), total - 1)
        self.assertNotIn(reverse('education:lesson_pdf', args=[self.lecon.pk]) + '?download=1', page)
        self.connecter(self.prof)
        page = self.client.get(reverse('education:niveau_detail', args=['1ere_bac_sc'])).content.decode()
        self.assertNotIn('data-verrou', page)
        detail = self.client.get(reverse('education:lesson_detail', args=[self.lecon.pk]))
        self.assertContains(detail, 'data-acces-lecon')
        self.assertContains(detail, '1BAC A')

    def test_eleve_de_deux_classes(self):
        classe_b = Classroom.objects.create(name='1BAC B', niveau='1ere_bac_sc', teacher=self.autre_prof)
        ClassroomMember.objects.create(classroom=classe_b, user=self.eleve)
        AccesLecon.objects.create(classroom=classe_b, lesson=self.lecon, decision=AccesLecon.OUVERT)
        self.assertEqual(lecons_ouvertes(self.eleve), frozenset({self.lecon.pk}))
