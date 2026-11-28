"""Quiz en direct (écran projeté + téléphone), carnet de notes (saisie au clavier) et correction
dessinée sur une copie photographiée, dans un vrai navigateur."""
import os
import shutil
import tempfile
from pathlib import Path

from django.conf import settings
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.files.base import ContentFile
from django.test import override_settings
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from accounts.models import User
from classrooms.models import Classroom, ClassroomMember, ColonneNote, NoteSaisie
from devoirs.models import Devoir, FichierRendu, RenduDevoir
from education.models import Course, Lesson
from quizzes.models import Choice, LiveParticipant, LiveSession, Question, Quiz

from .test_chat_moderation import SingleThreadLiveServer

MEDIA = tempfile.mkdtemp(prefix='edubac-direct-nav-')
IMAGE = Path(settings.BASE_DIR) / 'static' / 'img' / 'guide' / 'connexion.png'


def session_pour(user):
    session = SessionStore()
    session['user_id'] = user.pk
    session.save()
    return session.session_key


@override_settings(MEDIA_ROOT=MEDIA)
class DirectCarnetBrowserTests(StaticLiveServerTestCase):
    server_thread_class = SingleThreadLiveServer

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        self.prof = User.objects.create_user(username='prof-d', email='prof-d@example.test', role='teacher')
        self.eleve = User.objects.create_user(username='eleve-d', email='eleve-d@example.test', role='student',
                                              first_name='Omar', last_name='Alaoui')
        self.classe = Classroom.objects.create(name='TC1', niveau='tronc_commun', teacher=self.prof)
        ClassroomMember.objects.create(classroom=self.classe, user=self.eleve)
        course = Course.objects.create(name='Maths', niveau='tronc_commun')
        lesson = Lesson.objects.create(course=course, title='Les réels', order=1, content='')
        self.quiz = Quiz.objects.create(title='Calcul mental', lesson=lesson, created_by=self.prof, seconds_per_question=30)
        q = Question.objects.create(quiz=self.quiz, order=1, text='Combien font $2+3$ ?')
        Choice.objects.create(question=q, text='5', is_correct=True, order=0)
        Choice.objects.create(question=q, text='6', is_correct=False, order=1)
        self.session_prof = session_pour(self.prof)
        self.session_eleve = session_pour(self.eleve)

    def navigateur(self, pw):
        return pw.chromium.launch(executable_path=os.environ.get('CHROMIUM_EXECUTABLE') or shutil.which('chromium'),
                                  headless=True, args=['--no-sandbox'])

    def page(self, nav, session, largeur=1280, hauteur=800, mobile=False):
        contexte = nav.new_context(viewport={'width': largeur, 'height': hauteur}, is_mobile=mobile, has_touch=mobile)
        contexte.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': session, 'url': self.live_server_url}])
        page = contexte.new_page()
        page.route('https://fonts.googleapis.com/**', lambda route: route.abort())
        page.route('https://fonts.gstatic.com/**', lambda route: route.abort())
        erreurs = []
        page.on('pageerror', lambda exc: erreurs.append(str(exc)))
        return page, erreurs

    def test_partie_en_direct(self):
        with sync_playwright() as pw:
            nav = self.navigateur(pw)
            ecran, erreurs = self.page(nav, self.session_prof, 1366, 768)
            ecran.goto(self.live_server_url + reverse('quizzes:live_launch', args=[self.quiz.pk]))
            ecran.get_by_role('button', name='Ouvrir la salle d’attente').click()
            expect(ecran.locator('.direct-code-geant')).to_be_visible()
            tel, erreurs_tel = self.page(nav, self.session_eleve, 390, 820, True)
            tel.goto(self.live_server_url + reverse('accounts:dashboard'))
            tel.locator('.direct-bandeau').click()
            expect(tel.locator('.direct-message-grand')).to_contain_text('Tu es dans la partie')
            expect(ecran.locator('.direct-nom-puce')).to_have_text('Omar Alaoui')
            ecran.get_by_role('button', name='▶ Commencer').click()
            expect(ecran.locator('.direct-enonce .katex')).to_be_visible()
            tel.locator('.direct-choix', has_text='5').click()
            # Seul joueur à avoir répondu : la réponse s'affiche d'elle-même.
            expect(tel.locator('.direct-message-grand.juste')).to_contain_text('Juste !')
            expect(ecran.locator('.direct-choix.est-juste')).to_contain_text('5')
            expect(ecran.locator('.direct-classement')).to_contain_text('Omar Alaoui')
            ecran.get_by_role('button', name='Classement final 🏆').click()
            expect(ecran.locator('.direct-fin')).to_contain_text('Classement final')
            expect(tel.locator('.direct-message-grand')).to_contain_text('1er sur 1')
            self.assertEqual(erreurs + erreurs_tel, [])
            nav.close()
        self.assertEqual(LiveSession.objects.get().state, LiveSession.FINI)
        self.assertGreater(LiveParticipant.objects.get().score, 500)

    def test_carnet_saisie_au_clavier(self):
        autre = User.objects.create_user(username='eleve-e', email='e@example.test', role='student', last_name='Zed')
        ClassroomMember.objects.create(classroom=self.classe, user=autre)
        colonne = ColonneNote.objects.create(classe=self.classe, titre='Contrôle 1')
        with sync_playwright() as pw:
            nav = self.navigateur(pw)
            page, erreurs = self.page(nav, self.session_prof)
            page.goto(self.live_server_url + reverse('classrooms:carnet', args=[self.classe.pk]))
            cases = page.locator('.carnet-saisie')
            cases.nth(0).fill('15,5')
            cases.nth(0).press('Enter')                     # enregistre et passe à l'élève suivant
            expect(cases.nth(1)).to_be_focused()
            cases.nth(1).fill('12')
            cases.nth(1).press('Enter')
            expect(cases.nth(1)).to_have_class('carnet-saisie est-ok')
            expect(page.locator('[data-moyenne-classe]')).to_have_text('13,75')
            cases.nth(0).fill('30')
            cases.nth(0).press('Tab')
            expect(cases.nth(0)).to_have_class('carnet-saisie est-erreur')
            self.assertEqual(erreurs, [])
            nav.close()
        self.assertEqual(sorted(str(n.note) for n in NoteSaisie.objects.filter(colonne=colonne)), ['12.00', '15.50'])

    def test_corriger_une_copie_au_stylo(self):
        devoir = Devoir.objects.create(teacher=self.prof, titre='DM 1')
        devoir.classes.add(self.classe)
        rendu = RenduDevoir.objects.create(devoir=devoir, eleve=self.eleve)
        page_copie = FichierRendu(rendu=rendu, nom='page1.png', taille=IMAGE.stat().st_size)
        page_copie.fichier.save('page1.png', ContentFile(IMAGE.read_bytes()))
        with sync_playwright() as pw:
            nav = self.navigateur(pw)
            page, erreurs = self.page(nav, self.session_prof)
            page.goto(self.live_server_url + reverse('devoirs:annoter', args=[page_copie.pk]))
            expect(page.locator('[data-etat]')).to_have_text('')
            boite = page.locator('[data-dessin]').bounding_box()
            page.mouse.move(boite['x'] + 60, boite['y'] + 80)
            page.mouse.down()
            for i in range(20):
                page.mouse.move(boite['x'] + 60 + i * 10, boite['y'] + 80 + (i % 4) * 5)
            page.mouse.up()
            page.locator('[data-outil="juste"]').click()
            page.mouse.click(boite['x'] + 200, boite['y'] + 160)
            page.locator('[data-enregistrer-btn]').click()
            expect(page.locator('[data-etat]')).to_contain_text('Correction enregistrée')
            self.assertEqual(erreurs, [])
            nav.close()
        page_copie.refresh_from_db()
        self.assertTrue(page_copie.annotee)
        self.assertEqual(page_copie.annotee.read()[:8], b'\x89PNG\r\n\x1a\n')
