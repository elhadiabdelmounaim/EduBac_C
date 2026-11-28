"""Nouveaux outils dans un vrai navigateur : copie photographiée rendue par l'élève (téléphone),
sondage et éditeur de formules dans le salon, révision des erreurs, reprise de la lecture."""
import os
import shutil
import tempfile
from pathlib import Path

from django.conf import settings
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from playwright.sync_api import expect, sync_playwright

from accounts.models import User
from chat.models import ChatPollVote, ClassChatRoom
from classrooms.models import Classroom, ClassroomMember
from devoirs.models import Devoir, RenduDevoir
from education.models import Course, Lesson
from quizzes.models import Attempt, Choice, Question, Quiz, StudentAnswer

from .test_chat_moderation import SingleThreadLiveServer

MEDIA = tempfile.mkdtemp(prefix='edubac-outils-nav-')


def session_pour(user):
    session = SessionStore()
    session['user_id'] = user.pk
    session.save()
    return session.session_key


@override_settings(MEDIA_ROOT=MEDIA)
class OutilsClasseBrowserTests(StaticLiveServerTestCase):
    server_thread_class = SingleThreadLiveServer

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        self.prof = User.objects.create_user(username='prof-o', email='prof-o@example.test', role='teacher',
                                             first_name='Nadia', last_name='Benali')
        self.eleve = User.objects.create_user(username='eleve-o', email='eleve-o@example.test', role='student',
                                              first_name='Omar', last_name='Alaoui')
        self.classe = Classroom.objects.create(name='1bac1', niveau='1ere_bac_sc', teacher=self.prof)
        ClassroomMember.objects.create(classroom=self.classe, user=self.eleve)
        ClassChatRoom.get_or_create_for(self.classe)
        self.devoir = Devoir.objects.create(teacher=self.prof, titre='DM 4 — Barycentre',
                                            date_limite=timezone.now() + timezone.timedelta(days=2))
        self.devoir.classes.add(self.classe)
        course = Course.objects.create(name='Mathématiques', niveau='1ere_bac_sc')
        self.lesson = Lesson.objects.create(course=course, title='Les suites numériques', order=5, content='')
        quiz = Quiz.objects.create(title='Suites', lesson=self.lesson, created_by=self.prof, status='published')
        q = Question.objects.create(quiz=quiz, order=1, text='Calculer $u_2$ si $u_n=2n$.', regle='On remplace $n$ par 2.',
                                    explanation='$u_2=2\\times 2=4$.')
        Choice.objects.create(question=q, text='4', is_correct=True)
        Choice.objects.create(question=q, text='2', is_correct=False)
        tentative = Attempt.objects.create(quiz=quiz, student=self.eleve, submitted_at=timezone.now())
        StudentAnswer.objects.create(attempt=tentative, question=q, answer='2', is_correct=False)
        from cahier.models import AccesLecon
        AccesLecon.objects.create(classroom=self.classe, lesson=self.lesson, decision=AccesLecon.OUVERT)
        self.session_prof = session_pour(self.prof)
        self.session_eleve = session_pour(self.eleve)
        self.dossier = Path(tempfile.mkdtemp(prefix='edubac-photos-'))
        (self.dossier / 'page1.jpg').write_bytes(b'\xff\xd8\xff\xe0 page 1')
        (self.dossier / 'page2.jpg').write_bytes(b'\xff\xd8\xff\xe0 page 2')

    def tearDown(self):
        shutil.rmtree(self.dossier, ignore_errors=True)
        super().tearDown()

    def navigateur(self, pw):
        return pw.chromium.launch(executable_path=os.environ.get('CHROMIUM_EXECUTABLE') or shutil.which('chromium'),
                                  headless=True, args=['--no-sandbox'])

    def page(self, nav, session, largeur=1280, hauteur=900, mobile=False):
        contexte = nav.new_context(viewport={'width': largeur, 'height': hauteur}, is_mobile=mobile, has_touch=mobile)
        contexte.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': session, 'url': self.live_server_url}])
        page = contexte.new_page()
        page.route('https://fonts.googleapis.com/**', lambda route: route.abort())
        page.route('https://fonts.gstatic.com/**', lambda route: route.abort())
        erreurs = []
        page.on('pageerror', lambda exc: erreurs.append(str(exc)))
        return page, erreurs

    def test_l_eleve_photographie_deux_pages_et_rend(self):
        with sync_playwright() as pw:
            nav = self.navigateur(pw)
            tel, erreurs = self.page(nav, self.session_eleve, 390, 820, True)
            tel.goto(self.live_server_url + reverse('accounts:dashboard'))
            expect(tel.locator('#devoirsTitle')).to_be_visible()
            tel.get_by_role('link', name='Rendre').click()
            # Deux photos successives : la seconde s'ajoute à la première.
            tel.locator('input[data-photo]').set_input_files(str(self.dossier / 'page1.jpg'))
            tel.locator('input[data-photo]').set_input_files(str(self.dossier / 'page2.jpg'))
            expect(tel.locator('[data-choisis] li')).to_have_count(2)
            tel.locator('[data-envoyer]').click()
            expect(tel.locator('.alert-success')).to_contain_text('2 fichiers envoyés')
            expect(tel.locator('.dv-statut.est-rendu')).to_be_visible()
            self.assertLessEqual(tel.evaluate('document.documentElement.scrollWidth'), 390)
            self.assertEqual(erreurs, [])
            nav.close()
        self.assertEqual(RenduDevoir.objects.get().fichiers.count(), 2)

    def test_sondage_vote_et_formule(self):
        with sync_playwright() as pw:
            nav = self.navigateur(pw)
            prof, erreurs = self.page(nav, self.session_prof)
            prof.goto(self.live_server_url + reverse('chat:room', args=[self.classe.pk]))
            prof.locator('#chatPollBtn').click()
            prof.locator('[data-modele*="compris"]').click()
            prof.locator('#chatPollDialog button[type=submit]').click()
            expect(prof.locator('.chat-poll')).to_contain_text('Avez-vous compris ?')
            # Formule : la palette insère du LaTeX entre $ et l'aperçu le rend.
            prof.locator('#chatInput').fill('Rappel : ')
            prof.locator('.chat-formula-btn').click()
            prof.locator('.chat-formula-key[title^="Fraction"]').click()
            expect(prof.locator('#chatInput')).to_have_value('Rappel : $\\frac{a}{b}$')
            expect(prof.locator('.chat-formula-preview .katex')).to_have_count(1)
            self.assertEqual(erreurs, [])

            eleve, erreurs_eleve = self.page(nav, self.session_eleve, 390, 820, True)
            eleve.goto(self.live_server_url + reverse('chat:room', args=[self.classe.pk]))
            eleve.locator('.chat-poll-option', has_text='Oui').click()
            expect(eleve.locator('.chat-poll-option.is-mine')).to_contain_text('1 · 100 %')
            self.assertEqual(erreurs_eleve, [])
            nav.close()
        self.assertEqual(ChatPollVote.objects.get().option, 0)

    def test_revoir_mes_erreurs(self):
        with sync_playwright() as pw:
            nav = self.navigateur(pw)
            page, erreurs = self.page(nav, self.session_eleve)
            page.goto(self.live_server_url + reverse('quizzes:review_mistakes'))
            expect(page.locator('.rv-err-enonce .katex').first).to_be_visible()
            page.locator('.rv-err-choix button[data-juste="0"]').click()
            expect(page.locator('.rv-err-verdict.ko')).to_be_visible()
            expect(page.locator('.rv-err-choix button[data-juste="1"]')).to_have_class('est-juste')
            expect(page.locator('.rv-err-bloc.solution .katex').first).to_be_visible()
            page.get_by_role('button', name='Terminer').click()
            expect(page.locator('#errCarte')).to_contain_text('0 / 1 juste')
            self.assertEqual(erreurs, [])
            nav.close()

    def test_reprendre_la_lecture_du_cours(self):
        with sync_playwright() as pw:
            nav = self.navigateur(pw)
            page, erreurs = self.page(nav, self.session_eleve)
            url = self.live_server_url + reverse('education:lesson_course_html', args=[self.lesson.pk])
            page.goto(url)
            page.wait_for_selector('html.pagine-pret', state='attached', timeout=30000)
            for _ in range(3):
                page.get_by_role('button', name='Page suivante').click()
                page.wait_for_timeout(400)
            page.goto(url)
            page.wait_for_selector('html.pagine-pret', state='attached', timeout=30000)
            expect(page.locator('.reprise-aller')).to_have_text('Reprendre à la page 4')
            page.locator('.reprise-aller').click()
            expect(page).to_have_url(url + '#p4')
            # Le micro de recherche est là, et pas au vidéoprojecteur.
            expect(page.locator('#rvFab')).to_be_visible()
            self.assertEqual(erreurs, [])
            nav.close()
