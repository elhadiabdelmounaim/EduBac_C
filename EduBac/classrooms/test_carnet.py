"""Carnet de notes : colonnes saisies, devoirs et quiz, moyennes pondérées, visibilité pour
les élèves, droits, export Excel."""
import json
from decimal import Decimal
from io import BytesIO

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from devoirs.models import Devoir, RenduDevoir
from education.models import Course, Lesson
from quizzes.models import Attempt, Quiz, QuizAssignment

from .models import Classroom, ClassroomMember, ColonneNote, NoteSaisie


@override_settings(ALLOWED_HOSTS=['testserver'])
class CarnetTests(TestCase):
    def setUp(self):
        self.prof = User.objects.create_user(username='prof', email='prof@example.test', role='teacher')
        self.autre = User.objects.create_user(username='prof2', email='prof2@example.test', role='teacher')
        self.classe = Classroom.objects.create(name='1bac1', niveau='1ere_bac_sc', teacher=self.prof)
        self.a = User.objects.create_user(username='a', email='a@example.test', role='student', first_name='Amal', last_name='A')
        self.b = User.objects.create_user(username='b', email='b@example.test', role='student', first_name='Badr', last_name='B')
        for e in (self.a, self.b):
            ClassroomMember.objects.create(classroom=self.classe, user=e)
        course = Course.objects.create(name='Maths', niveau='1ere_bac_sc')
        lesson = Lesson.objects.create(course=course, title='Suites', order=5, content='')
        self.quiz = Quiz.objects.create(title='Quiz suites', lesson=lesson, created_by=self.prof, status='published')
        QuizAssignment.objects.create(quiz=self.quiz, student=self.a)
        self.devoir = Devoir.objects.create(teacher=self.prof, titre='DM 1')
        self.devoir.classes.add(self.classe)

    def connecter(self, user):
        session = self.client.session
        session['user_id'] = user.pk
        session.save()

    def url(self, nom='carnet'):
        return reverse(f'classrooms:{nom}', args=[self.classe.pk])

    def ajouter(self, **data):
        return self.client.post(self.url(), {'action': 'ajouter', **data})

    def saisir(self, colonne, eleve, note):
        return self.client.post(self.url('carnet_note'), json.dumps({'colonne': colonne.pk, 'eleve': eleve.pk, 'note': note}),
                                content_type='application/json')

    def test_colonnes_et_moyennes_ponderees(self):
        self.connecter(self.prof)
        page = self.client.get(self.url())
        self.assertContains(page, 'DM 1')                 # proposé dans « Ajouter »
        self.assertContains(page, 'Quiz suites')
        self.ajouter(source='manuel', titre='Contrôle 1')
        self.ajouter(source='devoir', devoir=self.devoir.pk)
        self.ajouter(source='quiz', quiz=self.quiz.pk)
        controle, dm, qz = ColonneNote.objects.order_by('pk')
        ColonneNote.objects.filter(pk=controle.pk).update(coefficient=2)
        r = self.saisir(controle, self.a, '14,5').json()
        self.assertEqual(r['note'], '14,5')
        RenduDevoir.objects.create(devoir=self.devoir, eleve=self.a, note=Decimal('17'), corrige_le=timezone.now())
        Attempt.objects.create(quiz=self.quiz, student=self.a, score=75, submitted_at=timezone.now())
        page = self.client.get(self.url())
        # (14,5×2 + 17 + 15) / 4 = 15,25
        self.assertContains(page, '15,25')
        self.assertContains(page, '>15<')                   # quiz 75 % → 15/20
        # Hors moyenne : la colonne quiz ne compte plus.
        self.client.post(self.url(), {'action': 'regler', 'colonne': qz.pk, 'titre': 'Quiz', 'coefficient': '1'})
        self.assertContains(self.client.get(self.url()), '15,33')   # (29 + 17) / 3

    def test_saisie_invalide_ou_hors_classe(self):
        self.connecter(self.prof)
        self.ajouter(source='manuel', titre='Oral')
        col = ColonneNote.objects.get()
        self.assertEqual(self.saisir(col, self.a, '25').status_code, 400)
        intrus = User.objects.create_user(username='x', email='x@example.test', role='student')
        self.assertEqual(self.saisir(col, intrus, '10').status_code, 404)
        self.saisir(col, self.a, '12')
        self.saisir(col, self.a, '')                       # effacer
        self.assertIsNone(NoteSaisie.objects.get().note)

    def test_eleve_voit_seulement_les_colonnes_publiees_et_ses_notes(self):
        self.connecter(self.prof)
        self.ajouter(source='manuel', titre='Contrôle 1')
        self.ajouter(source='manuel', titre='Brouillon')
        c1, c2 = ColonneNote.objects.order_by('pk')
        self.saisir(c1, self.a, '16')
        self.saisir(c1, self.b, '9')
        self.saisir(c2, self.a, '3')
        self.client.post(self.url(), {'action': 'regler', 'colonne': c1.pk, 'titre': 'Contrôle 1', 'coefficient': '1',
                                      'dans_moyenne': '1', 'visible_eleves': '1'})
        self.client.get(self.url())                       # affiche (et consomme) les messages du professeur
        self.connecter(self.a)
        page = self.client.get(reverse('classrooms:mes_notes'))
        self.assertContains(page, 'Contrôle 1')
        self.assertContains(page, '16/20')
        self.assertNotContains(page, 'Brouillon')
        self.assertNotContains(page, '9/20')
        self.assertNotEqual(self.client.get(self.url()).status_code, 200)

    def test_autre_professeur_refuse_et_excel(self):
        self.connecter(self.autre)
        self.assertEqual(self.client.get(self.url()).status_code, 404)
        self.connecter(self.prof)
        self.ajouter(source='manuel', titre='Contrôle 1')
        self.saisir(ColonneNote.objects.get(), self.a, '18')
        r = self.client.get(self.url('carnet_excel'))
        self.assertEqual(r.status_code, 200)
        from openpyxl import load_workbook
        ws = load_workbook(BytesIO(r.content)).active
        self.assertEqual(ws['A1'].value, 'Élève')
        self.assertEqual(ws['B2'].value, 18.0)
