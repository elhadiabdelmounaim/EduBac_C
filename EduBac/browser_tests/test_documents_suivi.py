"""Leçon : boutons COURS / EXERCICES (ouvrir, télécharger) ; séance : durée réalisée et barre de
progression de la leçon (panneau du cours, puis page du niveau dans le cahier de textes)."""
import os
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from playwright.sync_api import sync_playwright

from classrooms.models import Classroom
from education.media_library import chapter_relative
from education.models import Course, Lesson, Resources


class DocumentsEtSuiviBrowserTests(StaticLiveServerTestCase):
    def setUp(self):
        media = TemporaryDirectory()
        self.addCleanup(media.cleanup)
        reglage = override_settings(MEDIA_ROOT=media.name)
        reglage.enable()
        self.addCleanup(reglage.disable)
        course = Course.objects.create(name='Mathématiques', niveau='1ere_bac_sc')
        self.lesson = Lesson.objects.create(title='Le produit scalaire dans le plan', content='Contenu.',
                                            course=course, order=4, duree_prevue_minutes=360)
        dossier = Path(media.name) / chapter_relative(self.lesson)
        (dossier / 'Exercices').mkdir(parents=True)
        (dossier / 'Exercices' / 'serie-1.pdf').write_bytes(b'%PDF-1.4\n%%EOF')
        Resources.objects.create(lesson=self.lesson, name='Résumé du cours', categorie='cours',
                                 file=SimpleUploadedFile('resume.pdf', b'%PDF-1.4\n%%EOF'))
        prof = get_user_model().objects.create_user(username='prof', email='prof@example.test', role='teacher')
        Classroom.objects.create(name='1BAC SE 2', niveau='1ere_bac_sc', teacher=prof)
        session = SessionStore()
        session['user_id'] = prof.pk
        session.save()
        self.session_key = session.session_key
        self.playwright = sync_playwright().start()
        executable = os.environ.get('CHROMIUM_EXECUTABLE') or shutil.which('chromium')
        self.browser = self.playwright.chromium.launch(executable_path=executable, headless=True, args=['--no-sandbox'])

    def tearDown(self):
        self.browser.close()
        self.playwright.stop()
        super().tearDown()

    def page(self, url, width=1280, height=900):
        context = self.browser.new_context(viewport={'width': width, 'height': height}, accept_downloads=True)
        context.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': self.session_key,
                              'url': self.live_server_url}])
        page = context.new_page()
        page.route('https://fonts.googleapis.com/**', lambda route: route.abort())
        page.route('https://fonts.gstatic.com/**', lambda route: route.abort())
        erreurs = []
        page.on('pageerror', lambda exc: erreurs.append(str(exc)))
        page.goto(self.live_server_url + url)
        return page, erreurs

    def test_course_and_exercise_buttons(self):
        for largeur in (1280, 390):
            page, erreurs = self.page(reverse('education:lesson_detail', args=[self.lesson.pk]), largeur, 860)
            cours, exercices = page.locator('#bouton-cours'), page.locator('#bouton-exercices')
            self.assertTrue(page.is_hidden('#docs-cours'))
            self.assertTrue(page.is_hidden('#docs-exercices'))
            cours.click()
            self.assertEqual(cours.get_attribute('aria-expanded'), 'true')
            self.assertTrue(page.is_visible('#docs-cours'))
            self.assertIn('Cours en ligne', page.inner_text('#docs-cours'))
            self.assertIn('Résumé du cours', page.inner_text('#docs-cours'))
            exercices.click()
            self.assertTrue(page.is_hidden('#docs-cours'))
            self.assertIn('serie-1.pdf', page.inner_text('#docs-exercices'))
            # Ouvrir : le PDF s'affiche dans un nouvel onglet ; Télécharger : fichier enregistré.
            with page.context.expect_page() as onglet:
                page.click('#docs-exercices a:has-text("Ouvrir")')
            onglet.value.wait_for_load_state()
            self.assertIn('serie-1.pdf', onglet.value.url)
            onglet.value.close()
            with page.expect_download() as fichier:
                page.click('#docs-exercices a:has-text("Télécharger")')
            self.assertEqual(fichier.value.suggested_filename, 'serie-1.pdf')
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth - innerWidth'), 0)
            self.assertEqual(erreurs, [])
            page.context.close()

    def test_session_duration_updates_the_progress_bar(self):
        page, erreurs = self.page(reverse('education:lesson_course_html', args=[self.lesson.pk]), 1440, 900)
        page.wait_for_selector('html.pagine-pret', state='attached', timeout=30000)
        page.click('.topbar-seance')
        page.wait_for_selector('#seanceArbre .seance-racine')
        page.fill('#seanceDate', '2026-11-02')
        page.dispatch_event('#seanceDate', 'change')
        page.wait_for_selector('#seanceSuivi .suivi')
        self.assertIn('6 h', page.inner_text('#seanceLecon'))
        # Cocher propose une durée (temps prévu des éléments), que l'enseignant corrige.
        page.locator('#seanceArbre .niveau-1').first.locator(':scope > .seance-ligne input').check()
        self.assertTrue(int(page.input_value('#seanceDuree')) > 0)
        page.fill('#seanceDuree', '90')
        page.click('#seanceEnregistrer')
        page.wait_for_selector('.seance-message.succes')
        suivi = page.inner_text('#seanceSuivi')
        self.assertIn('25,00 %', suivi)
        self.assertIn('75,00 % restant', suivi)
        self.assertIn('1 h 30', suivi)
        self.assertIn('4 h 30', suivi)
        self.assertEqual(float(page.get_attribute('#seanceSuivi .suivi-barre', 'aria-valuenow')), 25.0)
        # Deuxième séance : 2 h → 3 h 30 réalisées (58,33 %).
        page.fill('#seanceDate', '2026-11-09')
        page.dispatch_event('#seanceDate', 'change')
        page.wait_for_timeout(400)
        page.locator('#seanceArbre .niveau-1').nth(1).locator(':scope > .seance-ligne input').check()
        page.fill('#seanceDuree', '120')
        page.click('#seanceEnregistrer')
        page.wait_for_selector('.seance-message.succes')
        page.wait_for_function("document.querySelector('#seanceSuivi').innerText.includes('58,33')")
        self.assertIn('2 h 30', page.inner_text('#seanceSuivi'))
        self.assertEqual(erreurs, [])
        # Page du niveau : progression de la leçon, sur ordinateur et sur téléphone.
        for largeur in (1280, 390):
            niveau, erreurs = self.page(reverse('cahier:niveau', args=['1ere_bac_sc']), largeur, 860)
            bloc = niveau.locator('.cahier-suivi').first
            self.assertIn('58,33 %', bloc.inner_text())
            self.assertIn('41,67 % restant', bloc.inner_text())
            largeur_barre = niveau.evaluate(
                "() => { const b = document.querySelector('.cahier-suivi .suivi-barre');"
                " return document.querySelector('.cahier-suivi .suivi-fait').offsetWidth / b.offsetWidth; }")
            self.assertAlmostEqual(largeur_barre, 0.5833, delta=0.02)
            self.assertLessEqual(niveau.evaluate('document.documentElement.scrollWidth - innerWidth'), 0)
            self.assertEqual(erreurs, [])
            niveau.context.close()
