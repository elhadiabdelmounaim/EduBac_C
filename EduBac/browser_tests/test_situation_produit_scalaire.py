"""Produit scalaire (1ère Bac SE) : situation problème 3D en ouverture du cours — étapes au
clavier, réponses, calculs (100 J ; nul à 90° ; négatif si l'angle est obtus), minuteur de
30 min au vidéoprojecteur, puis entrée dans la partie I. Ordinateur, téléphone, projecteur."""
import os
import shutil

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.urls import reverse
from playwright.sync_api import sync_playwright

from education.models import Course, Lesson

DEBORDE = ("[...document.querySelectorAll('.feuille')].filter(f => { const c = f.querySelector('.feuille-corps');"
           " return c.scrollHeight > c.clientHeight + 1; }).length")


class SituationProduitScalaireBrowserTests(StaticLiveServerTestCase):
    def setUp(self):
        course = Course.objects.create(name='Mathématiques', niveau='1ere_bac_sc')
        self.lesson = Lesson.objects.create(title='Le produit scalaire dans le plan', content='', course=course, order=4)
        prof = get_user_model().objects.create_user(username='prof', email='prof@example.test', role='teacher')
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

    def open(self, width, height, teacher=False):
        context = self.browser.new_context(viewport={'width': width, 'height': height})
        if teacher:
            context.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': self.session_key,
                                  'url': self.live_server_url}])
        page = context.new_page()
        page.route('https://fonts.googleapis.com/**', lambda route: route.abort())
        page.route('https://fonts.gstatic.com/**', lambda route: route.abort())
        errors = []
        page.on('pageerror', lambda exc: errors.append(str(exc)))
        page.goto(self.live_server_url + reverse('education:lesson_course_html', args=[self.lesson.pk]))
        page.wait_for_selector('html.pagine-pret', state='attached', timeout=30000)
        page.wait_for_selector('[data-situation][data-pret]', state='attached', timeout=15000)
        return page, errors

    def compteur(self, page):
        return page.evaluate("document.querySelector('[data-compteur]').textContent")

    def assert_toutes_les_etapes_tiennent(self, page, vue):
        """Chaque étape, réponse affichée : la page de l'activité ne déborde jamais."""
        page.evaluate("(() => { const e = document.querySelector('[data-situation]').etapesInternes;"
                      " while (e.reculer()) {} })()")
        self.assertIn('Étape 1 / 8', self.compteur(page))
        for k in range(8):
            page.evaluate("document.querySelector('.sp-etape.active [data-reveler]')?.click()")
            deborde = page.evaluate("(() => { const c = document.querySelector('[data-situation]')"
                                    ".closest('.feuille-corps'); return c.scrollHeight - c.clientHeight; })()")
            self.assertLessEqual(deborde, 1, f'{vue}, étape {k + 1}')
            page.evaluate("document.querySelector('[data-suivante]').click()")

    def test_steps_answers_and_values(self):
        page, errors = self.open(1280, 900)
        # Première partie du cours, juste après la couverture et le sommaire.
        self.assertEqual(page.evaluate("document.querySelector('.chap').id"), 's0')
        page.keyboard.press('ArrowRight')
        page.wait_for_timeout(600)
        self.assertTrue(page.locator('.feuille.visible [data-situation]').count())
        self.assertIn('Étape 1 / 8', self.compteur(page))
        self.assertIn('F = 40 N · θ = 60° · AB = 5 m', page.inner_text('[data-mesures]'))
        # → : étape suivante ; sur une question, → montre d'abord la réponse.
        page.keyboard.press('ArrowRight')
        self.assertIn('Étape 2 / 8', self.compteur(page))
        self.assertFalse(page.locator('.sp-etape.active .sp-reponse.revelee').count())
        page.keyboard.press('ArrowRight')
        self.assertTrue(page.locator('.sp-etape.active .sp-reponse.revelee').count())
        self.assertIn('Étape 2 / 8', self.compteur(page))
        page.keyboard.press('ArrowLeft')
        self.assertIn('Étape 1 / 8', self.compteur(page))
        page.click('[data-suivante]')
        page.click('[data-suivante]')
        page.click('[data-suivante]')
        self.assertIn('Question 2', self.compteur(page))
        self.assertTrue(page.is_visible('[data-lancer]') or not page.evaluate(
            "document.querySelector('[data-situation]').classList.contains('en-3d')"))
        page.click('.sp-etape.active [data-reveler]')
        self.assertIn('100', page.inner_text('.sp-etape.active .sp-reponse'))
        # Manipulation : le travail mesuré et F × AB × cos θ coïncident.
        page.click('[data-suivante]')
        self.assertTrue(page.is_visible('[data-reglages]'))
        self.assertEqual(page.inner_text('[data-v="W"]'), 'Fx × AB = 20 × 5 = 100 J')
        self.assertEqual(page.inner_text('[data-v="produit"]'), '40 × 5 × 0,5 = 100')
        page.fill('[data-r="F"]', '80')
        page.dispatch_event('[data-r="F"]', 'input')
        self.assertEqual(page.inner_text('[data-v="produit"]'), '80 × 5 × 0,5 = 200')
        # Généralisation : signe du produit scalaire.
        page.click('[data-suivante]')
        page.click('[data-suivante]')
        self.assertIn('Généraliser', self.compteur(page))
        page.click('[data-angle="90"]')
        self.assertIn('= 0 : nul', page.inner_text('[data-v="signe"]'))
        page.click('[data-angle="135"]')
        self.assertIn('négatif', page.inner_text('[data-v="signe"]'))
        page.click('[data-angle="0"]')
        self.assertIn('positif', page.inner_text('[data-v="signe"]'))
        # Dernière étape, puis « Commencer le cours » : partie I.
        page.click('[data-suivante]')
        self.assertIn('Étape 8 / 8', self.compteur(page))
        self.assert_toutes_les_etapes_tiennent(page, 'ordinateur')
        page.click('[data-commencer]')
        page.wait_for_timeout(600)
        self.assertIn('Étude analytique du produit scalaire', page.inner_text('.feuille.visible .feuille-corps'))
        self.assertEqual(page.evaluate(DEBORDE), 0)
        self.assertEqual(errors, [])

    def test_projector_timer_and_phone(self):
        page, errors = self.open(1920, 1080, teacher=True)
        normal = page.evaluate("document.querySelectorAll('.feuille').length")
        page.click('#coursPresenter')
        page.wait_for_function("document.documentElement.classList.contains('presentation')"
                               f" && document.querySelectorAll('.feuille').length !== {normal}")
        page.wait_for_timeout(900)
        page.select_option('select', 's0')
        page.wait_for_timeout(600)
        page.keyboard.press('ArrowRight')            # l'activité apparaît : son minuteur (30 min) démarre
        page.wait_for_timeout(600)
        self.assertTrue(page.is_visible('#minuteur'))
        self.assertIn('Activité 1', page.inner_text('#minuteurNom'))
        self.assertIn(page.inner_text('#minuteurTemps')[:2], ('30', '29'))
        for _ in range(3):
            page.keyboard.press('ArrowRight')
        self.assertIn('Étape 3 / 8', self.compteur(page))
        self.assertEqual(page.evaluate(DEBORDE), 0)
        self.assert_toutes_les_etapes_tiennent(page, 'projecteur')
        self.assertEqual(errors, [])
        page.context.close()
        for largeur, hauteur in ((390, 844), (390, 760)):
            phone, errors = self.open(largeur, hauteur)
            self.assertEqual(phone.evaluate(DEBORDE), 0)
            self.assert_toutes_les_etapes_tiennent(phone, f'téléphone {largeur}×{hauteur}')
            phone.context.close()
        phone, errors = self.open(390, 760)
        self.assertLessEqual(phone.evaluate('document.documentElement.scrollWidth - innerWidth'), 0)
        self.assertEqual(errors, [])
