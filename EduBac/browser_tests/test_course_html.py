"""Cours en ligne (HTML) présenté en cahier : pages à la taille de l'écran, tournées
avec les boutons, le clavier ou le doigt ; MathJax local ; rien n'est perdu ni ne déborde."""
import os
import shutil

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.urls import reverse
from playwright.sync_api import sync_playwright

from education.models import Course, Lesson

BLOCS = 50          # blocs (définitions, propositions…) du cours « Produit scalaire »
POINTS = 115        # éléments de liste <li> du cours


class CourseHtmlBrowserTests(StaticLiveServerTestCase):
    def setUp(self):
        course = Course.objects.create(name='Mathématiques', niveau='1ere_bac_sc')
        self.lesson = Lesson.objects.create(
            title='Le produit scalaire dans le plan', content='', course=course, order=4)
        self.playwright = sync_playwright().start()
        executable = os.environ.get('CHROMIUM_EXECUTABLE') or shutil.which('chromium')
        self.browser = self.playwright.chromium.launch(
            executable_path=executable, headless=True, args=['--no-sandbox'])

    def tearDown(self):
        self.browser.close()
        self.playwright.stop()
        super().tearDown()

    def open(self, width, height, theme=None, hash='', touch=False):
        context = self.browser.new_context(viewport={'width': width, 'height': height}, has_touch=touch)
        page = context.new_page()
        # Les polices Google sont facultatives : on ne dépend pas du réseau.
        page.route('https://fonts.googleapis.com/**', lambda route: route.abort())
        page.route('https://fonts.gstatic.com/**', lambda route: route.abort())
        errors = []
        page.on('pageerror', lambda exc: errors.append(str(exc)))
        if theme:
            page.add_init_script(f"localStorage.setItem('edubac-theme', '{theme}')")
        url = reverse('education:lesson_course_html', args=[self.lesson.pk])
        page.goto(self.live_server_url + url + hash)
        page.wait_for_selector('html.pagine-pret', state='attached', timeout=30000)
        return page, errors

    def current(self, page):
        return page.evaluate("[...document.querySelectorAll('.feuille.visible')].map("
                             "p => [...document.querySelectorAll('.feuille')].indexOf(p) + 1)")

    def assert_pages_sound(self, page):
        state = page.evaluate("""() => {
            const pages = [...document.querySelectorAll('.feuille')];
            const W = document.documentElement.clientWidth;
            return {
                pages: pages.length,
                blocs: document.querySelectorAll('.feuille .bloc:not(.suite)').length,
                points: document.querySelectorAll('.feuille li').length,
                sommaire: document.querySelectorAll('.feuille .bloc-sommaire li').length,
                parties: document.querySelectorAll('.feuille-corps > h2').length,
                source: document.querySelector('#source').textContent.trim().length,
                deborde: pages.filter(p => p.classList.contains('deborde')).length,
                coupe: pages.filter(p => { const c = p.querySelector('.feuille-corps');
                                           return c.scrollHeight > c.clientHeight + 1; }).length,
                pageScroll: document.documentElement.scrollHeight - document.documentElement.clientHeight,
                largeur: document.documentElement.scrollWidth - W,
                erreurs: document.querySelectorAll('mjx-merror, [data-mjx-error]').length,
                formules: document.querySelectorAll('.feuille mjx-container').length,
            };
        }""")
        self.assertGreater(state['pages'], 10)
        self.assertEqual(state['blocs'], BLOCS)                 # aucun bloc perdu ni dupliqué
        self.assertEqual(state['points'], POINTS + 9)           # + 9 entrées du sommaire
        self.assertEqual(state['sommaire'], 9)
        self.assertEqual(state['parties'], 9)                   # I à IX
        self.assertEqual(state['source'], 0)                    # tout est passé dans les pages
        self.assertEqual(state['deborde'], 0)
        self.assertEqual(state['coupe'], 0)                     # aucune page tronquée
        self.assertLessEqual(state['pageScroll'], 0)            # pas de défilement vertical
        self.assertLessEqual(state['largeur'], 0)
        self.assertEqual(state['erreurs'], 0)
        self.assertGreater(state['formules'], 100)
        return state

    def test_desktop_spread_buttons_keyboard_and_summary(self):
        page, errors = self.open(1280, 860)
        self.assertEqual(errors, [])
        state = self.assert_pages_sound(page)
        # Une seule page à la fois, même sur grand écran.
        self.assertEqual(self.current(page), [1])
        self.assertTrue(page.is_disabled('#pagePrev'))
        self.assertEqual(page.inner_text('#pageNum'), f"Page 1 / {state['pages']}")
        self.assertEqual(page.locator('[data-stats] .stat').all_inner_texts(),
                         ['3\ndéfinitions', '15\npropositions', '14\napplications'])
        # La feuille courante se tourne en découvrant la suivante…
        page.click('#pageNext')
        self.assertEqual(self.current(page), [2])
        self.assertTrue(page.evaluate("document.querySelectorAll('.feuille')[0].classList.contains('tourne')"))
        self.assertTrue(page.evaluate("document.querySelectorAll('.feuille')[1].classList.contains('dessous')"))
        page.wait_for_function("!document.querySelector('.feuille.tourne')")
        self.assertFalse(page.locator('.feuille').nth(0).is_visible())
        page.keyboard.press('ArrowRight')
        self.assertEqual(self.current(page), [3])
        # … et la précédente se rabat par-dessus pour revenir.
        page.keyboard.press('ArrowLeft')
        self.assertEqual(self.current(page), [2])
        self.assertTrue(page.evaluate("document.querySelectorAll('.feuille')[1].classList.contains('revient')"))
        self.assertIn('#p2', page.url)
        # Clics rapides : chaque clic tourne une page, sans en sauter ni rester bloqué.
        for _ in range(3):
            page.click('#pageNext')
        self.assertEqual(self.current(page), [5])
        page.wait_for_function("!document.querySelector('.feuille.tourne, .feuille.revient, .feuille.dessous')")
        self.assertEqual(page.locator('.feuille:visible').count(), 1)
        # « Aller à la partie » et sommaire de la couverture.
        page.select_option('#pageChapitre', 's6')
        first = self.current(page)[0]
        self.assertIn('VI', page.locator('.feuille').nth(first - 1).locator('.feuille-tete').inner_text())
        page.keyboard.press('Home')
        # Le sommaire est sur la couverture ou la page qui la suit.
        if not page.locator('.feuille.visible .bloc-sommaire').count():
            page.keyboard.press('ArrowRight')
        page.wait_for_function("!document.querySelector('.feuille.tourne, .feuille.revient')")
        page.click('.feuille.visible .bloc-sommaire a[href="#s4"]')
        self.assertEqual(page.input_value('#pageChapitre'), 's4')
        page.keyboard.press('End')
        self.assertTrue(page.is_disabled('#pageNext'))
        page.click('.feuille.visible [data-haut]')
        self.assertEqual(self.current(page), [1])
        # Les pages cachées ne reçoivent pas le focus clavier.
        self.assertTrue(page.evaluate("document.querySelectorAll('.feuille')[4].inert"))
        page.click('#coursTheme')
        self.assertEqual(page.evaluate("localStorage.getItem('edubac-theme')"), 'dark')
        self.assertEqual(errors, [])

    def test_phone_single_page_swipe_and_resize(self):
        page, errors = self.open(390, 760, theme='dark', touch=True)
        self.assertEqual(errors, [])
        self.assertEqual(page.evaluate("document.documentElement.getAttribute('data-theme')"), 'dark')
        state = self.assert_pages_sound(page)
        self.assertEqual(self.current(page), [1])
        swipe = """dx => { const s = document.getElementById('scene');
            const opts = (x) => ({pointerType: 'touch', clientX: x, clientY: 400, bubbles: true});
            s.dispatchEvent(new PointerEvent('pointerdown', opts(200)));
            s.dispatchEvent(new PointerEvent('pointerup', opts(200 + dx))); }"""
        page.evaluate(swipe, -120)
        self.assertEqual(self.current(page), [2])
        page.evaluate(swipe, 120)
        self.assertEqual(self.current(page), [1])
        page.evaluate(swipe, -20)                                # trop court : rien ne change
        self.assertEqual(self.current(page), [1])
        # Ouvert sur une page donnée, puis l'écran pivote : la lecture reprend au même endroit.
        page.select_option('#pageChapitre', 's5')
        anchor = page.evaluate("document.querySelector('.feuille.visible .feuille-corps').firstElementChild.textContent")
        page.set_viewport_size({'width': 760, 'height': 390})
        page.wait_for_function(f"document.querySelectorAll('.feuille').length !== {state['pages']}")
        page.wait_for_timeout(300)
        visible = page.evaluate("document.querySelector('.feuille.visible .feuille-corps').textContent")
        self.assertIn(anchor.strip()[:40], visible)
        self.assertEqual(errors, [])

    def test_opening_on_a_page_from_the_address(self):
        page, errors = self.open(1280, 860, hash='#p5')
        self.assertEqual(self.current(page), [5])
        page.close()
        page, errors = self.open(390, 760, hash='#s9')
        self.assertIn('IX', page.locator('.feuille.visible .feuille-tete').inner_text())
        self.assertEqual(errors, [])

    def test_projector_presentation_mode(self):
        page, errors = self.open(1920, 1080)
        normal = page.evaluate("document.querySelectorAll('.feuille').length")
        page.click('#coursPresenter')
        page.wait_for_function(f"document.documentElement.classList.contains('presentation')"
                               f" && document.querySelectorAll('.feuille').length !== {normal}")
        self.assertFalse(page.locator('.topbar').is_visible())
        self.assert_pages_sound(page)
        # Une seule grande page à la fois, texte lisible de loin.
        self.assertEqual(self.current(page), [1])
        size = page.evaluate("parseFloat(getComputedStyle(document.querySelector('.feuille-corps')).fontSize)")
        self.assertGreaterEqual(size, 26)
        # Télécommande de présentation : Page suivante / Page précédente.
        page.keyboard.press('PageDown')
        self.assertEqual(self.current(page), [2])
        page.keyboard.press('PageUp')
        self.assertEqual(self.current(page), [1])
        # Les éléments de la page qui apparaît sont animés.
        page.keyboard.press('ArrowRight')
        self.assertTrue(page.evaluate("document.querySelector('.feuille.visible').classList.contains('entree')"))
        # Écran noir (B), rallumé par n'importe quelle touche, sans changer de page.
        page.keyboard.press('b')
        self.assertTrue(page.evaluate("document.documentElement.classList.contains('noir')"))
        page.keyboard.press('ArrowRight')
        self.assertFalse(page.evaluate("document.documentElement.classList.contains('noir')"))
        self.assertEqual(self.current(page), [2])
        # La barre s'efface quand la souris ne bouge plus, puis revient.
        page.wait_for_function("document.documentElement.classList.contains('calme')", timeout=5000)
        page.mouse.move(500, 500)
        self.assertFalse(page.evaluate("document.documentElement.classList.contains('calme')"))
        # Quitter : retour au cahier, au même endroit.
        anchor = page.evaluate("document.querySelector('.feuille.visible .feuille-corps').textContent.trim().slice(0, 40)")
        page.keyboard.press('Escape')
        page.wait_for_function("!document.documentElement.classList.contains('presentation')")
        self.assertEqual(len(self.current(page)), 1)
        self.assertIn(anchor, page.evaluate(
            "[...document.querySelectorAll('.feuille.visible .feuille-corps')].map(c => c.textContent).join(' ')"))
        self.assertEqual(errors, [])
