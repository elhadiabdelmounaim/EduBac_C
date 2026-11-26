"""Cours en ligne « Suites numériques » (1ère Bac Sciences, leçon 5) : toutes les pages sont
complètes, en lecture, sur téléphone et au vidéoprojecteur, avec le minuteur des 7 heures."""
import os
import shutil

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.urls import reverse
from playwright.sync_api import sync_playwright

from education.models import Course, Lesson

BLOCS = 50          # activités, définitions, propriétés, méthodes, exemples, applications…
PARTIES = 6         # I à VI


from .acces_eleve import session_eleve_avec_acces

class SuitesCourseBrowserTests(StaticLiveServerTestCase):
    def setUp(self):
        course = Course.objects.create(name='Mathématiques', niveau='1ere_bac_sc')
        self.lesson = Lesson.objects.create(
            title='Les suites numériques', content='', course=course, order=5)
        prof = get_user_model().objects.create_user(username='prof', email='prof@example.test', role='teacher')
        session = SessionStore()
        session['user_id'] = prof.pk
        session.save()
        self.teacher_session = session.session_key
        self.student_session = session_eleve_avec_acces([self.lesson])
        self.playwright = sync_playwright().start()
        executable = os.environ.get('CHROMIUM_EXECUTABLE') or shutil.which('chromium')
        self.browser = self.playwright.chromium.launch(
            executable_path=executable, headless=True, args=['--no-sandbox'])

    def tearDown(self):
        self.browser.close()
        self.playwright.stop()
        super().tearDown()

    def open(self, width, height, teacher=False, theme=None):
        context = self.browser.new_context(viewport={'width': width, 'height': height})
        if teacher:
            context.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': self.teacher_session,
                                  'url': self.live_server_url}])
        else:
            context.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': self.student_session,
                                  'url': self.live_server_url}])
        page = context.new_page()
        page.route('https://fonts.googleapis.com/**', lambda route: route.abort())
        page.route('https://fonts.gstatic.com/**', lambda route: route.abort())
        errors = []
        page.on('pageerror', lambda exc: errors.append(str(exc)))
        if theme:
            page.add_init_script(f"localStorage.setItem('edubac-theme', '{theme}')")
        page.goto(self.live_server_url + reverse('education:lesson_course_html', args=[self.lesson.pk]))
        page.wait_for_selector('html.pagine-pret', state='attached', timeout=30000)
        return page, errors

    def assert_pages_sound(self, page):
        state = page.evaluate("""() => {
            const pages = [...document.querySelectorAll('.feuille')];
            return {
                pages: pages.length,
                blocs: document.querySelectorAll('.feuille .bloc:not(.suite)').length,
                parties: document.querySelectorAll('.feuille-corps > h2').length,
                source: document.querySelector('#source').textContent.trim().length,
                deborde: pages.filter(p => p.classList.contains('deborde')).length,
                coupe: pages.filter(p => { const c = p.querySelector('.feuille-corps');
                                           return c.scrollHeight > c.clientHeight + 1; }).length,
                largeur: document.documentElement.scrollWidth - document.documentElement.clientWidth,
                erreurs: document.querySelectorAll('mjx-merror, [data-mjx-error]').length,
                formules: document.querySelectorAll('.feuille mjx-container').length,
                brut: [...document.querySelectorAll('.feuille-corps')].some(c => /\\\\[(\\[]/.test(c.textContent)),
            };
        }""")
        self.assertGreater(state['pages'], 8)
        self.assertEqual(state['blocs'], BLOCS)             # aucun bloc perdu ni dupliqué
        self.assertEqual(state['parties'], PARTIES)
        self.assertEqual(state['source'], 0)
        self.assertEqual(state['deborde'], 0)
        self.assertEqual(state['coupe'], 0)                 # aucune page tronquée
        self.assertLessEqual(state['largeur'], 0)
        self.assertEqual(state['erreurs'], 0)               # \N et les autres macros sont connues
        self.assertFalse(state['brut'])                     # aucune formule laissée en LaTeX
        self.assertGreater(state['formules'], 300)
        return state

    def test_reading_and_phone(self):
        page, errors = self.open(1280, 860)
        self.assert_pages_sound(page)
        self.assertEqual(page.locator('[data-stats] .stat').all_inner_texts(),
                         ['6\ndéfinitions', '7\npropriétés', '14\napplications'])
        self.assertEqual(page.locator('.feuille .tableau table tbody tr').count(), 6)
        self.assertEqual(errors, [])
        phone, errors = self.open(390, 844, theme='dark')
        self.assert_pages_sound(phone)
        self.assertEqual(errors, [])

    def test_projector_with_timer(self):
        page, errors = self.open(1920, 1080, teacher=True)
        normal = page.evaluate("document.querySelectorAll('.feuille').length")
        page.click('#coursPresenter')
        page.wait_for_function(f"document.documentElement.classList.contains('presentation')"
                               f" && document.querySelectorAll('.feuille').length !== {normal}")
        self.assert_pages_sound(page)
        # Chaque application seule sur sa page, voilée jusqu'au clic.
        self.assertEqual(page.locator('.feuille.page-app').count(), 14)
        # Les 7 heures de la répartition sont réparties entre les 49 blocs.
        minutage = page.evaluate("JSON.parse(document.getElementById('cours-minutage').textContent)")
        self.assertEqual(len(minutage), BLOCS)
        self.assertEqual(sum(minutage.values()), 7 * 60)
        # Activité 1 (premier bloc de la partie I) : son temps prévu s'affiche, puis décompte.
        page.wait_for_timeout(400)
        cible = page.evaluate("[...document.querySelectorAll('.feuille')]"
                              ".findIndex(f => f.querySelector('.bloc[data-cle=\"s1-b1\"]'))")
        for _ in range(cible):
            page.keyboard.press('ArrowDown')
        page.wait_for_timeout(1400)
        page.keyboard.press('ArrowRight')
        self.assertTrue(page.is_visible('#minuteur'))
        self.assertEqual(page.inner_text('#minuteurNom'), 'Activité 1')
        self.assertEqual(page.inner_text('#minuteurTemps'), f"{minutage['s1-b1']}:00")
        self.assertEqual(errors, [])
