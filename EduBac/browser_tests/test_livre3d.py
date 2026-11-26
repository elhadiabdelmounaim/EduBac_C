"""Livre 3D (Three.js) : chargement sans erreur, prédiction puis rabat, figures cliquables
(sans confondre clic et glissement), tampon, tour de page, sommaire, démonstration guidée
interrompue par l'utilisateur, retour à la vue d'ensemble, animations réduites, téléphone."""
import os
import shutil

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.urls import reverse
from playwright.sync_api import sync_playwright

from education.models import Course, Lesson


from .acces_eleve import session_eleve_avec_acces

class Livre3DBrowserTests(StaticLiveServerTestCase):
    def setUp(self):
        course = Course.objects.create(name='Mathématiques', niveau='1ere_bac_sc')
        self.lesson = Lesson.objects.create(
            title='Le produit scalaire dans le plan', content='', course=course, order=4)
        self.student_session = session_eleve_avec_acces([self.lesson])
        self.playwright = sync_playwright().start()
        executable = os.environ.get('CHROMIUM_EXECUTABLE') or shutil.which('chromium')
        self.browser = self.playwright.chromium.launch(
            executable_path=executable, headless=True, args=['--no-sandbox'])

    def tearDown(self):
        self.browser.close()
        self.playwright.stop()
        super().tearDown()

    def open(self, width=1440, height=900, touch=False, reduced=False):
        context = self.browser.new_context(viewport={'width': width, 'height': height}, has_touch=touch,
                                           reduced_motion='reduce' if reduced else 'no-preference')
        context.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': self.student_session,
                              'url': self.live_server_url}])
        page = context.new_page()
        page.route('https://fonts.googleapis.com/**', lambda route: route.abort())
        page.route('https://fonts.gstatic.com/**', lambda route: route.abort())
        errors = []
        page.on('pageerror', lambda exc: errors.append(str(exc)))
        page.on('console', lambda m: errors.append(m.text)
                if m.type == 'error' and 'ERR_FAILED' not in m.text else None)
        page.goto(self.live_server_url + reverse('education:lesson_book_3d', args=[self.lesson.pk]))
        page.wait_for_selector('.livre-pret', state='attached', timeout=30000)
        self.idle(page)
        return page, errors

    def idle(self, page):
        page.wait_for_function('!Livre3D.occupe()', timeout=20000)
        page.wait_for_timeout(300)

    def point(self, page, cible):
        return page.evaluate(f"Livre3D.ecran('{cible}')")

    def test_lesson_prediction_flap_figures_and_stamp(self):
        page, errors = self.open()
        self.assertTrue(page.locator('#scene3d canvas').is_visible())
        self.assertEqual(page.inner_text('.pg-titre'), 'Expression analytique du produit scalaire')
        self.assertGreater(page.locator('.page-gauche mjx-container').count(), 5)
        self.assertEqual(page.locator('.page-gauche mjx-merror, .page-gauche [data-mjx-error]').count(), 0)
        # Le rabat reste verrouillé tant qu'aucune prédiction n'est faite.
        self.assertTrue(page.is_disabled('.pg-rabat'))
        page.click('.pg-choix button:has-text("24")')
        self.assertTrue(page.locator('.pg-choix button:has-text("24")').get_attribute('class').count('faux'))
        self.assertIn('juste', page.locator('.pg-choix button:has-text("orthogonaux")').get_attribute('class'))
        self.assertTrue(page.is_disabled('.pg-choix button:has-text("10")'))
        page.click('.pg-rabat')
        self.assertEqual(page.get_attribute('.pg-rabat', 'aria-expanded'), 'true')
        # Glisser sur une figure fait tourner la vue mais ne la déclenche pas.
        p = self.point(page, 'u')
        page.mouse.move(p['x'], p['y'])
        page.mouse.down()
        page.mouse.move(p['x'] + 60, p['y'] + 25, steps=6)
        page.mouse.up()
        self.assertEqual(page.evaluate('Livre3D.progression().faits'), {})
        page.click('#hudVue')
        self.idle(page)
        # Un vrai clic déclenche chaque figure ; les trois explorées encrent le tampon.
        for cible in ('u', 'v', 'bocal'):
            p = self.point(page, cible)
            page.mouse.click(p['x'], p['y'])
            page.wait_for_timeout(250)
        prog = page.evaluate('Livre3D.progression()')
        self.assertEqual(sorted(prog['faits']['s1']), ['bocal', 'u', 'v'])
        self.assertTrue(prog['tampons']['s1'])
        self.assertIn('encre', page.get_attribute('.pg-tampon', 'class'))
        # La prédiction est conservée après rechargement.
        page.reload()
        page.wait_for_selector('.livre-pret', state='attached', timeout=30000)
        self.assertTrue(page.is_disabled('.pg-choix button:has-text("24")'))
        self.assertFalse(page.is_disabled('.pg-rabat'))
        self.assertEqual(errors, [])

    def test_page_turn_summary_keyboard_and_all_figures(self):
        page, errors = self.open()
        page.click('#hudSuiv')
        page.wait_for_function('Livre3D.occupe()')
        self.idle(page)
        self.assertEqual(page.evaluate('Livre3D.lecon()'), 1)
        self.assertIn('Expression de cos et sin', page.inner_text('#hudTitre'))
        self.assertIn('cos et sin', page.inner_text('.pg-titre'))
        page.keyboard.press('ArrowRight')
        self.idle(page)
        self.assertEqual(page.evaluate('Livre3D.lecon()'), 2)
        page.keyboard.press('ArrowLeft')
        self.idle(page)
        self.assertEqual(page.evaluate('Livre3D.lecon()'), 1)
        # Sommaire : neuf leçons, saut direct.
        page.click('#hudSommaire')
        self.assertEqual(page.locator('#tiroirListe button').count(), 9)
        page.click('#tiroirListe button:has-text("Tangente")')
        self.idle(page)
        self.assertEqual(page.evaluate('Livre3D.lecon()'), 8)
        self.assertTrue(page.is_disabled('#hudSuiv'))
        # Chaque figure de chaque leçon réagit (déclenchement direct, comme la démonstration).
        for i in range(9):
            page.evaluate(f'Livre3D.aller({i})')
            self.idle(page)
            for cible in page.evaluate(f"JSON.parse(document.getElementById('livre-donnees').textContent).spreads[{i}].scene.interactions"):
                page.evaluate(f"Livre3D.declencher('{cible}')")
            page.wait_for_timeout(200)
        prog = page.evaluate('Livre3D.progression()')
        self.assertEqual(len(prog['tampons']), 9)
        page.click('#hudSommaire')
        self.assertEqual(page.locator('#tiroirListe .fait:text("✓")').count(), 9)
        self.assertEqual(errors, [])

    def test_guided_demo_stops_when_the_user_takes_over_and_reset_view(self):
        page, errors = self.open()
        start = page.evaluate('Livre3D.camera()')
        page.click('#hudDemo')
        self.assertTrue(page.evaluate('Livre3D.demo()'))
        self.assertEqual(page.get_attribute('#hudDemo', 'aria-pressed'), 'true')
        page.wait_for_function("!document.getElementById('livreLegende').hidden")
        page.wait_for_function(f"Math.abs(Livre3D.camera().d - {start['d']}) > 0.3", timeout=15000)
        # L'utilisateur fait glisser : la démonstration s'arrête, la caméra lui revient.
        page.mouse.move(700, 450)
        page.mouse.down()
        page.mouse.move(780, 470, steps=6)
        page.mouse.up()
        self.assertFalse(page.evaluate('Livre3D.demo()'))
        self.assertTrue(page.is_hidden('#livreLegende'))
        moved = page.evaluate('Livre3D.camera()')
        self.assertNotAlmostEqual(moved['x'], start['x'], places=2)
        # Molette : zoom borné.
        for _ in range(30):
            page.mouse.wheel(0, 600)
        page.wait_for_timeout(600)
        self.assertLessEqual(page.evaluate('Livre3D.camera().d'), 7)
        self.assertGreaterEqual(page.evaluate('Livre3D.camera().y'), 0.12)
        page.click('#hudVue')
        self.idle(page)
        back = page.evaluate('Livre3D.camera()')
        for axe in 'xyz':
            self.assertAlmostEqual(back[axe], start[axe], places=2)
        self.assertEqual(errors, [])

    def test_reduced_motion_turns_pages_instantly(self):
        page, errors = self.open(reduced=True)
        self.assertIn('mouvement-reduit', page.evaluate('document.documentElement.className'))
        self.assertEqual(page.get_attribute('#hudMouvement', 'aria-pressed'), 'true')
        page.click('#hudSuiv')
        page.wait_for_function('Livre3D.lecon() === 1 && !Livre3D.occupe()', timeout=5000)
        page.click('#hudDemo')
        page.wait_for_timeout(400)
        self.assertTrue(page.evaluate('Livre3D.demo()'))
        start = page.evaluate('Livre3D.camera()')
        page.wait_for_timeout(1500)
        # Pas de déplacement automatique de la caméra.
        self.assertEqual(page.evaluate('Livre3D.camera()'), start)
        page.click('#hudContraste')
        self.assertIn('contraste', page.evaluate('document.documentElement.className'))
        self.assertEqual(errors, [])

    def test_phone_layout(self):
        page, errors = self.open(390, 844, touch=True)
        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth - innerWidth'), 0)
        box = page.locator('#livreHud').bounding_box()
        self.assertGreaterEqual(box['x'], 0)
        self.assertLessEqual(box['x'] + box['width'], 390)
        page.click('#hudSuiv')
        self.idle(page)
        self.assertEqual(page.evaluate('Livre3D.lecon()'), 1)
        self.assertEqual(errors, [])
