"""Devoirs et quiz à plusieurs classes, dans un vrai navigateur : le professeur publie un devoir
pour deux classes avec un énoncé et une correction verrouillée ; l'élève (téléphone) voit
l'énoncé mais pas la correction ; la barre du bas a l'entrée « Devoirs » ; un quiz part vers
deux classes cochées après confirmation."""
import os
import shutil
import tempfile
from pathlib import Path

from django.conf import settings
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from accounts.models import User
from classrooms.models import Classroom, ClassroomMember
from devoirs.models import Devoir
from education.models import Course, Lesson
from quizzes.models import Choice, Question, Quiz, QuizAssignment

MEDIA = tempfile.mkdtemp(prefix='edubac-devoirs-navigateur-')


def session_pour(user):
    session = SessionStore()
    session['user_id'] = user.pk
    session.save()
    return session.session_key


@override_settings(MEDIA_ROOT=MEDIA)
class DevoirsBrowserTests(StaticLiveServerTestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        self.prof = User.objects.create_user(username='prof-dv', email='prof-dv@example.test', role='teacher')
        self.a = Classroom.objects.create(name='1bac1', niveau='1ere_bac_sc', teacher=self.prof)
        self.b = Classroom.objects.create(name='1bac2', niveau='1ere_bac_sc', teacher=self.prof)
        self.eleve_a = User.objects.create_user(username='eleve-a', email='ea@example.test', role='student')
        self.eleve_b = User.objects.create_user(username='eleve-b', email='eb@example.test', role='student')
        ClassroomMember.objects.create(classroom=self.a, user=self.eleve_a)
        ClassroomMember.objects.create(classroom=self.b, user=self.eleve_b)
        self.session_prof = session_pour(self.prof)
        self.session_eleve = session_pour(self.eleve_b)
        self.dossier = Path(tempfile.mkdtemp(prefix='edubac-fichiers-'))
        (self.dossier / 'Enonce_DM3.pdf').write_bytes(b'%PDF-1.4 enonce')
        (self.dossier / 'Correction_DM3.pdf').write_bytes(b'%PDF-1.4 correction')

    def tearDown(self):
        shutil.rmtree(self.dossier, ignore_errors=True)
        super().tearDown()

    def navigateur(self, pw):
        return pw.chromium.launch(
            executable_path=os.environ.get('CHROMIUM_EXECUTABLE') or shutil.which('chromium'),
            headless=True, args=['--no-sandbox'])

    def page(self, navigateur, session, largeur=1280, hauteur=900):
        contexte = navigateur.new_context(viewport={'width': largeur, 'height': hauteur})
        contexte.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': session, 'url': self.live_server_url}])
        page = contexte.new_page()
        erreurs = []
        page.on('pageerror', lambda exc: erreurs.append(str(exc)))
        return page, erreurs

    def test_publier_puis_l_eleve_ne_voit_pas_la_correction(self):
        with sync_playwright() as pw:
            nav = self.navigateur(pw)
            page, erreurs = self.page(nav, self.session_prof)
            page.goto(self.live_server_url + reverse('devoirs:creer'))
            page.fill('#dvTitre', 'DM 3 — Produit scalaire')
            page.fill('#dvDateLimite', '2030-12-07T08:00')
            page.get_by_role('button', name='Toutes').click()
            expect(page.locator('input[name="classes"]:checked')).to_have_count(2)
            page.set_input_files('#dvFichiers', str(self.dossier / 'Enonce_DM3.pdf'))
            page.set_input_files('#dvFichiersVerrou', str(self.dossier / 'Correction_DM3.pdf'))
            page.get_by_role('button', name='Publier le devoir').click()
            expect(page.locator('.alert-success')).to_contain_text('publié pour 1bac1, 1bac2 (2 élèves prévenus)')
            expect(page.locator('.dv-fichier.est-verrouille')).to_contain_text('Non visible par les élèves')
            self.assertEqual(erreurs, [])

            # Élève de 1bac2, sur téléphone : entrée « Devoirs » dans la barre du bas.
            tel, erreurs_tel = self.page(nav, self.session_eleve, largeur=390, hauteur=820)
            tel.goto(self.live_server_url + reverse('accounts:dashboard'))
            entree = tel.locator('.bottom-nav .bn-item[data-nav="devoirs"]')
            expect(entree).to_be_visible()
            entree.click()
            tel.locator('.dv-carte-titre').click()
            expect(tel.locator('.dv-fichier').first.locator('a.dv-fichier-nom')).to_have_text('Enonce_DM3.pdf')
            verrouille = tel.locator('.dv-fichier.est-verrouille')
            expect(verrouille).to_contain_text('Disponible plus tard')
            expect(verrouille.locator('a')).to_have_count(0)
            self.assertLessEqual(tel.evaluate('document.documentElement.scrollWidth'), 390)
            self.assertEqual(erreurs_tel, [])

            # Le professeur déverrouille : l'élève voit maintenant le lien.
            page.locator('summary', has_text='Déverrouiller').click()
            expect(page.locator('input[name="prevenir"]')).to_be_checked()      # élèves prévenus par défaut
            page.get_by_role('button', name='Rendre visible').click()
            expect(page.locator('.alert-success')).to_contain_text('visible par les élèves')
            tel.reload()
            expect(tel.locator('a.dv-fichier-nom', has_text='Correction_DM3.pdf')).to_be_visible()
            nav.close()
        devoir = Devoir.objects.get()
        self.assertEqual(set(devoir.classes.values_list('name', flat=True)), {'1bac1', '1bac2'})
        self.assertFalse(devoir.fichiers.filter(verrouille=True).exists())

    def test_barre_du_professeur_a_six_entrees_sur_petit_telephone(self):
        with sync_playwright() as pw:
            nav = self.navigateur(pw)
            tel, erreurs = self.page(nav, self.session_prof, largeur=360, hauteur=740)
            tel.goto(self.live_server_url + reverse('devoirs:index'))
            items = tel.locator('.bottom-nav .bn-item')
            expect(items).to_have_count(6)
            expect(tel.locator('.bottom-nav .bn-item[data-nav="devoirs"]')).to_have_class('bn-item active')
            boites = [items.nth(i).bounding_box() for i in range(6)]
            for gauche, droite in zip(boites, boites[1:]):
                self.assertLessEqual(gauche['x'] + gauche['width'], droite['x'] + 0.5)
            self.assertLessEqual(boites[-1]['x'] + boites[-1]['width'], 360)
            self.assertLessEqual(tel.evaluate('document.documentElement.scrollWidth'), 360)
            self.assertEqual(erreurs, [])
            nav.close()


class QuizDeuxClassesBrowserTests(StaticLiveServerTestCase):
    def setUp(self):
        self.prof = User.objects.create_user(username='prof-qz', email='prof-qz@example.test', role='teacher')
        course = Course.objects.create(name='Mathématiques', niveau='tronc_commun')
        lesson = Lesson.objects.create(course=course, title='Les nombres réels', order=1, content='.')
        self.quiz = Quiz.objects.create(title='Quiz réels', lesson=lesson, created_by=self.prof, status='draft')
        question = Question.objects.create(quiz=self.quiz, text='2+3 ?')
        Choice.objects.create(question=question, text='5', is_correct=True)
        Choice.objects.create(question=question, text='6', is_correct=False)
        for nom in ('TC A', 'TC B'):
            classe = Classroom.objects.create(name=nom, niveau='tronc_commun', teacher=self.prof)
            for i in range(2):
                eleve = User.objects.create_user(username=f'{nom}-{i}'.replace(' ', ''),
                                                 email=f'{nom}{i}@example.test'.replace(' ', ''), role='student')
                ClassroomMember.objects.create(classroom=classe, user=eleve)
        Classroom.objects.create(name='SM', niveau='1ere_bac_sm', teacher=self.prof)
        self.session = session_pour(self.prof)

    def test_cocher_deux_classes_et_confirmer(self):
        with sync_playwright() as pw:
            nav = pw.chromium.launch(executable_path=os.environ.get('CHROMIUM_EXECUTABLE') or shutil.which('chromium'),
                                     headless=True, args=['--no-sandbox'])
            contexte = nav.new_context(viewport={'width': 1280, 'height': 900})
            contexte.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': self.session,
                                   'url': self.live_server_url}])
            page = contexte.new_page()
            erreurs = []
            page.on('pageerror', lambda exc: erreurs.append(str(exc)))
            page.goto(f"{self.live_server_url}{reverse('quizzes:teacher_ai')}?quiz={self.quiz.pk}#quizAssign")
            expect(page.locator('.qb-class-card.is-disabled')).to_contain_text('SM')
            page.locator('.qb-class-card', has_text='TC A').click()
            page.locator('.qb-class-card', has_text='TC B').click()
            expect(page.locator('#assignQuizLabel')).to_have_text('Affecter le quiz à ces 2 classes')
            page.locator('#assignQuizBtn').click()
            expect(page.locator('#assignConfirmText')).to_contain_text('aux classes TC A et TC B ? 4 élèves')
            page.locator('#assignConfirmBtn').click()
            manage = reverse('quizzes:manage')
            page.wait_for_url(lambda url: manage in url)
            expect(page.locator('.alert-success')).to_contain_text('envoyé aux classes TC A et TC B')
            self.assertEqual(erreurs, [])
            nav.close()
        self.assertEqual(QuizAssignment.objects.filter(quiz=self.quiz).count(), 4)
