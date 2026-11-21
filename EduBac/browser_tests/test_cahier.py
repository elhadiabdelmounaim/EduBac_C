"""Cahier de textes : depuis le cours, l'enseignant choisit la date et la classe, coche ce
qu'il a traité (partie, sous-titres, blocs), enregistre, puis retrouve la séance dans le cahier."""
import os
import shutil

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.urls import reverse
from playwright.sync_api import sync_playwright

from classrooms.models import Classroom
from education.models import Course, Lesson


class CahierBrowserTests(StaticLiveServerTestCase):
    def setUp(self):
        course = Course.objects.create(name='Mathématiques', niveau='1ere_bac_sc')
        self.lesson = Lesson.objects.create(
            title='Le produit scalaire dans le plan', content='', course=course, order=4)
        prof = get_user_model().objects.create_user(username='prof', email='prof@example.test', role='teacher')
        Classroom.objects.create(name='1BAC SE 2', niveau='1ere_bac_sc', teacher=prof)
        Classroom.objects.create(name='TC 3', niveau='tronc_commun', teacher=prof)
        session = SessionStore()
        session['user_id'] = prof.pk
        session.save()
        self.session_key = session.session_key
        self.playwright = sync_playwright().start()
        executable = os.environ.get('CHROMIUM_EXECUTABLE') or shutil.which('chromium')
        self.browser = self.playwright.chromium.launch(
            executable_path=executable, headless=True, args=['--no-sandbox'])

    def tearDown(self):
        self.browser.close()
        self.playwright.stop()
        super().tearDown()

    def open(self, width=1440, height=900):
        context = self.browser.new_context(viewport={'width': width, 'height': height})
        context.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': self.session_key,
                              'url': self.live_server_url}])
        page = context.new_page()
        page.route('https://fonts.googleapis.com/**', lambda route: route.abort())
        page.route('https://fonts.gstatic.com/**', lambda route: route.abort())
        errors = []
        page.on('pageerror', lambda exc: errors.append(str(exc)))
        page.goto(self.live_server_url + reverse('education:lesson_course_html', args=[self.lesson.pk]))
        page.wait_for_selector('html.pagine-pret', state='attached', timeout=30000)
        return page, errors

    def test_record_session_from_the_course_and_read_it_in_the_journal(self):
        page, errors = self.open()
        page.click('.topbar-seance')
        page.wait_for_selector('#seanceArbre .seance-racine')
        # Classe du même niveau que la leçon proposée d'abord ; date du jour.
        self.assertIn('1BAC SE 2', page.locator('#seanceClasse option:checked').inner_text())
        self.assertTrue(page.input_value('#seanceDate'))
        self.assertEqual(page.locator('#seanceArbre .niveau-1').count(), 9)
        self.assertTrue(page.is_disabled('#seanceEnregistrer'))
        # Le panneau ne tourne pas les pages du cours quand on y tape.
        page.fill('#seanceDate', '2026-11-21')
        page.dispatch_event('#seanceDate', 'change')
        page.wait_for_timeout(300)
        # Cocher la partie I coche ses sous-titres et ses blocs.
        partie = page.locator('#seanceArbre .niveau-1').first
        partie.locator(':scope > .seance-ligne input').check()
        self.assertEqual(partie.locator('input[data-cle]:checked').count(), 7)
        # Partie II : on déplie et on ne coche que « Proposition ».
        deux = page.locator('#seanceArbre .niveau-1').nth(1)
        deux.locator('.seance-plier').first.click()
        deux.locator('label:has-text("Proposition") input').first.check()
        self.assertTrue(deux.locator(':scope > .seance-ligne input').evaluate('b => b.indeterminate'))
        self.assertIn('8 éléments', page.inner_text('#seanceCompte'))
        page.click('#seanceEnregistrer')
        page.wait_for_selector('.seance-message.succes')
        self.assertIn('21/11/2026', page.inner_text('#seanceMessage'))
        # Rouvrir la même date : la sélection est retrouvée.
        page.reload()
        page.wait_for_selector('html.pagine-pret', state='attached', timeout=30000)
        page.keyboard.press('s')
        page.wait_for_selector('#seanceArbre .seance-racine')
        page.fill('#seanceDate', '2026-11-21')
        page.dispatch_event('#seanceDate', 'change')
        page.wait_for_selector('.seance-message.info')
        self.assertEqual(page.locator('#seanceArbre input[data-cle]:checked').count(), 8)
        # Le cahier de textes montre la date, la classe et les titres traités.
        page.click('#seanceCahier')
        page.wait_for_selector('.cahier-seance')
        texte = page.inner_text('.cahier-seance')
        for attendu in ('Samedi 21 novembre 2026', '1BAC SE 2', 'I. Étude analytique du produit scalaire',
                        'I.1 Expression analytique du produit scalaire', 'Applications',
                        'II. Expression de cos et sin', 'Proposition'):
            self.assertIn(attendu, texte)
        self.assertEqual(errors, [])

    def test_panel_in_presentation_mode_and_on_phone(self):
        page, errors = self.open(1920, 1080)
        page.click('#coursPresenter')
        page.wait_for_function("document.documentElement.classList.contains('presentation')")
        page.mouse.move(500, 500)
        page.click('.pager-seance')
        page.wait_for_selector('#seanceArbre .seance-racine')
        avant = page.evaluate("document.querySelector('.feuille.visible') ? [...document.querySelectorAll('.feuille')].indexOf(document.querySelector('.feuille.visible')) : -1")
        page.locator('#seanceArbre .seance-plier').first.focus()
        page.keyboard.press('ArrowRight')
        self.assertEqual(page.evaluate("[...document.querySelectorAll('.feuille')].indexOf(document.querySelector('.feuille.visible'))"), avant)
        page.keyboard.press('Escape')
        self.assertTrue(page.is_hidden('#seancePanneau'))
        self.assertTrue(page.evaluate("document.documentElement.classList.contains('presentation')"))
        phone, errs = self.open(390, 760)
        self.assertLessEqual(phone.evaluate('document.documentElement.scrollWidth - innerWidth'), 0)
        phone.click('.pager-seance')
        phone.wait_for_selector('#seanceArbre .seance-racine')
        phone.wait_for_timeout(400)          # fin de l'animation d'entrée
        box = phone.locator('#seancePanneau').bounding_box()
        self.assertLessEqual(box['x'] + box['width'], 391)
        self.assertEqual(errors + errs, [])
