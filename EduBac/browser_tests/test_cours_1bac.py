"""Cours en ligne de 1ère Bac Sciences (générés depuis les fichiers LaTeX) : pour chaque leçon,
toutes les pages sont complètes et lisibles, en lecture, sur téléphone et au vidéoprojecteur."""
import os
import re
import shutil
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.urls import reverse
from playwright.sync_api import sync_playwright

from education.models import Course, Lesson

COURS = Path(settings.BASE_DIR) / 'templates' / 'education' / 'cours' / '1BAC_SE'
LECONS = [
    (1, 'Notions de logique', '01_notions-de-logique'),
    (2, 'Généralités sur les fonctions numériques', '02_generalites-sur-les-fonctions-numeriques'),
    (3, 'Le barycentre dans le plan', '03_le-barycentre-dans-le-plan'),
    (6, 'Calcul trigonométrique', '06_calcul-trigonometrique'),
    (7, 'La rotation dans le plan', '07_la-rotation-dans-le-plan'),
    (8, 'Les limites d’une fonction numérique', '08_les-limites-dune-fonction-numerique'),
    (9, 'La dérivation d’une fonction numérique', '09_la-derivation-dune-fonction-numerique'),
    (10, 'Étude et représentation d’une fonction', '10_etude-et-representation-dune-fonction'),
    (11, 'Vecteurs de l’espace', '11_vecteurs-de-lespace'),
    (12, 'Géométrie analytique de l’espace', '12_geometrie-analytique-de-lespace'),
]
ETAT = """() => {
    const pages = [...document.querySelectorAll('.feuille')];
    return {
        pages: pages.length,
        blocs: document.querySelectorAll('.feuille .bloc:not(.suite)').length,
        parties: document.querySelectorAll('.feuille-corps > h2').length,
        source: document.querySelector('#source').textContent.trim().length,
        deborde: pages.filter(p => p.classList.contains('deborde')).map(p => p.querySelector('.feuille-corps').textContent.trim().slice(0, 60)),
        coupe: pages.filter(p => { const c = p.querySelector('.feuille-corps');
                                   return c.scrollHeight > c.clientHeight + 1; }).length,
        largeur: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        erreurs: [...document.querySelectorAll('mjx-merror, [data-mjx-error]')].map(e => e.getAttribute('data-mjx-error') || e.textContent),
        brut: [...document.querySelectorAll('.feuille-corps')].map(c => c.textContent).join(' ').match(/\\\\[(\\[][^]{0,40}/g),
        figures: document.querySelectorAll('.feuille figure > svg').length,
    };
}"""


class Cours1BacBrowserTests(StaticLiveServerTestCase):
    def setUp(self):
        course = Course.objects.create(name='Mathématiques', niveau='1ere_bac_sc')
        self.lessons = [(Lesson.objects.create(title=t, content='', course=course, order=o), f)
                        for o, t, f in LECONS]
        prof = get_user_model().objects.create_user(username='prof', email='prof@example.test', role='teacher')
        session = SessionStore()
        session['user_id'] = prof.pk
        session.save()
        self.teacher_session = session.session_key
        self.playwright = sync_playwright().start()
        executable = os.environ.get('CHROMIUM_EXECUTABLE') or shutil.which('chromium')
        self.browser = self.playwright.chromium.launch(
            executable_path=executable, headless=True, args=['--no-sandbox'])

    def tearDown(self):
        self.browser.close()
        self.playwright.stop()
        super().tearDown()

    def open(self, lesson, width, height, teacher=False):
        context = self.browser.new_context(viewport={'width': width, 'height': height})
        if teacher:
            context.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': self.teacher_session,
                                  'url': self.live_server_url}])
        page = context.new_page()
        page.route('https://fonts.googleapis.com/**', lambda route: route.abort())
        page.route('https://fonts.gstatic.com/**', lambda route: route.abort())
        errors = []
        page.on('pageerror', lambda exc: errors.append(str(exc)))
        page.goto(self.live_server_url + reverse('education:lesson_course_html', args=[lesson.pk]))
        page.wait_for_selector('html.pagine-pret', state='attached', timeout=30000)
        return page, errors

    def check(self, page, fichier, vue):
        html = (COURS / (fichier + '.html')).read_text(encoding='utf-8')
        state = page.evaluate(ETAT)
        msg = '%s (%s)' % (fichier, vue)
        self.assertEqual(state['blocs'], html.count('<div class="bloc '), msg)
        self.assertEqual(state['parties'], html.count('<section class="chap"'), msg)
        self.assertEqual(state['source'], 0, msg)
        self.assertEqual(state['deborde'], [], msg)
        self.assertEqual(state['coupe'], 0, msg)
        self.assertLessEqual(state['largeur'], 0, msg)
        self.assertEqual(state['erreurs'], [], msg)
        self.assertIsNone(state['brut'], msg)
        self.assertEqual(state['figures'], len(re.findall(r'<figure[^>]*><svg', html)), msg)

    def test_reading_phone_and_projector(self):
        for lesson, fichier in self.lessons:
            with self.subTest(lecon=fichier):
                page, errors = self.open(lesson, 1280, 860)
                self.check(page, fichier, 'ordinateur')
                self.assertEqual(errors, [])
                page.context.close()
                phone, errors = self.open(lesson, 390, 844)
                self.check(phone, fichier, 'téléphone')
                self.assertEqual(errors, [])
                phone.context.close()
                pr, errors = self.open(lesson, 1920, 1080, teacher=True)
                normal = pr.evaluate("document.querySelectorAll('.feuille').length")
                pr.click('#coursPresenter')
                pr.wait_for_function("document.documentElement.classList.contains('presentation')"
                                     f" && document.querySelectorAll('.feuille').length !== {normal}")
                self.check(pr, fichier, 'projecteur')
                # Les heures de la répartition sont réparties entre tous les blocs.
                minutage = pr.evaluate("JSON.parse(document.getElementById('cours-minutage').textContent)")
                self.assertGreater(sum(minutage.values()), 0)
                self.assertEqual(errors, [])
                pr.context.close()
