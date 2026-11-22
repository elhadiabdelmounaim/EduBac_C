"""Cahier de textes : cartes des niveaux, séances d'un niveau, sélection et PDF (navigateur)."""
import datetime
import os
import shutil

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.urls import reverse
from playwright.sync_api import sync_playwright

from cahier.models import Seance, SeanceElement
from classrooms.models import Classroom
from education.models import Course, Lesson


class CahierNiveauxBrowserTests(StaticLiveServerTestCase):
    def setUp(self):
        course = Course.objects.create(name='Mathématiques', niveau='1ere_bac_sc')
        Course.objects.create(name='Maths TC', niveau='tronc_commun')
        lesson = Lesson.objects.create(title='Le produit scalaire dans le plan', content='', course=course, order=4)
        prof = get_user_model().objects.create_user(username='prof', email='prof@example.test', role='teacher')
        classe = Classroom.objects.create(name='1BAC SE 2', niveau='1ere_bac_sc', teacher=prof)
        self.ids = []
        for k in range(5):
            s = Seance.objects.create(teacher=prof, classroom=classe, lesson=lesson,
                                      date=datetime.date(2026, 11, 2) + datetime.timedelta(days=7 * k),
                                      observations='Observation %d' % (k + 1))
            SeanceElement.objects.create(seance=s, key='s1-b1', title='Application %d' % (k + 1),
                                         partie='I. Étude analytique', sous_titre='', order=0, minutes=30)
            self.ids.append(s.pk)
        session = SessionStore()
        session['user_id'] = prof.pk
        session.save()
        self.session = session.session_key
        self.playwright = sync_playwright().start()
        executable = os.environ.get('CHROMIUM_EXECUTABLE') or shutil.which('chromium')
        self.browser = self.playwright.chromium.launch(executable_path=executable, headless=True, args=['--no-sandbox'])

    def tearDown(self):
        self.browser.close()
        self.playwright.stop()
        super().tearDown()

    def open(self, width=1280, height=860):
        context = self.browser.new_context(viewport={'width': width, 'height': height}, accept_downloads=True)
        context.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': self.session, 'url': self.live_server_url}])
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda exc: errors.append(str(exc)))
        page.goto(self.live_server_url + reverse('cahier:index'))
        return page, errors

    def test_cards_selection_bar_and_downloads(self):
        page, errors = self.open()
        cartes = page.locator('.cahier-niveau')
        self.assertEqual(cartes.count(), 2)
        self.assertIn('5 séances', page.locator('.cahier-niveau', has_text='1ère Bac Sciences').inner_text())
        page.click('.cahier-niveau:has-text("1ère Bac Sciences")')
        page.wait_for_selector('.cahier-seance')
        self.assertEqual(page.locator('.cahier-seance').count(), 5)
        self.assertTrue(page.is_hidden('#cahierSelection'))
        # Cocher deux séances : la barre apparaît avec le nombre et le lien de la sélection.
        page.check('#seance-%d .cahier-coche' % self.ids[1])
        page.check('#seance-%d .cahier-coche' % self.ids[4])
        self.assertTrue(page.is_visible('#cahierSelection'))
        self.assertEqual(page.inner_text('#cahierCompte'), '2 séances sélectionnées')
        href = page.get_attribute('#cahierPdfSelection', 'href')
        self.assertIn('ids=%d' % self.ids[1], href)
        self.assertIn('ids=%d' % self.ids[4], href)
        with page.expect_download() as dl:
            page.click('#cahierPdfSelection')
        self.assertTrue(dl.value.suggested_filename.endswith('selection.pdf'))
        # La sélection est conservée après rechargement ; « Tout » puis « Désélectionner ».
        page.reload()
        self.assertEqual(page.inner_text('#cahierCompte'), '2 séances sélectionnées')
        page.click('#cahierTout')
        self.assertEqual(page.inner_text('#cahierCompte'), '5 séances sélectionnées')
        page.click('#cahierAucun')
        self.assertTrue(page.is_hidden('#cahierSelection'))
        # Une séance seule, puis tout le niveau.
        with page.expect_download() as dl:
            page.click('#seance-%d a:has-text("PDF")' % self.ids[0])
        self.assertTrue(dl.value.suggested_filename.startswith('seance-2026-11-02'))
        with page.expect_download() as dl:
            page.click('text=Télécharger toutes les séances')
        self.assertTrue(dl.value.suggested_filename.endswith('complet.pdf'))
        # Recherche.
        page.fill('.cahier-filtres input[name=q]', 'Observation 3')
        with page.expect_navigation():
            page.click('.cahier-filtres button[type=submit]')
        self.assertEqual(page.locator('.cahier-seance').count(), 1)
        self.assertEqual(errors, [])

    def test_phone_layout(self):
        page, errors = self.open(390, 800)
        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth - innerWidth'), 0)
        page.click('.cahier-niveau:has-text("1ère Bac Sciences")')
        page.wait_for_selector('.cahier-seance')
        page.check('#seance-%d .cahier-coche' % self.ids[0])
        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth - innerWidth'), 0)
        box = page.locator('#cahierSelection').bounding_box()
        self.assertLessEqual(box['x'] + box['width'], 391)
        self.assertEqual(errors, [])
