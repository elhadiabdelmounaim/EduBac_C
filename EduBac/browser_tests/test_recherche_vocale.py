"""Bouton micro flottant dans un vrai navigateur (la reconnaissance vocale est simulée) :
dictée → résultats → ouverture directe ; « Annuler » ; clavier sans micro (Firefox) ; paragraphe
ouvert et mis en évidence dans le cours en ligne ; place au-dessus de la barre du téléphone."""
import os
import re
import shutil

from django.conf import settings
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from accounts.models import User
from education.models import Course, Lesson

from .acces_eleve import session_eleve_avec_acces

# Reconnaissance vocale simulée : window.__dire(texte, final) fait « parler » l'utilisateur.
MICRO = """
class FausseReco {
  constructor() { window.__reco = this; }
  start() { setTimeout(() => { this.onstart && this.onstart(); window.__ecoute = true; }, 20); }
  abort() { this.onend && this.onend(); }
  stop() { this.onend && this.onend(); }
}
window.__dire = (texte, final) => {
  const r = window.__reco;
  r.onresult({ resultIndex: 0, results: [Object.assign([{ transcript: texte }], { isFinal: final })] });
  if (final) setTimeout(() => r.onend(), 30);
};
window.__refuser = () => { window.__reco.onerror({ error: 'not-allowed' }); window.__reco.onend(); };
window.SpeechRecognition = FausseReco;
window.webkitSpeechRecognition = FausseReco;
"""
SANS_MICRO = "delete window.SpeechRecognition; delete window.webkitSpeechRecognition;"


class RechercheVocaleBrowserTests(StaticLiveServerTestCase):
    def setUp(self):
        course = Course.objects.create(name='Mathématiques', niveau='1ere_bac_sc')
        self.lesson = Lesson.objects.create(title='Les suites numériques', content='', course=course, order=5)
        self.session = session_eleve_avec_acces([self.lesson])
        prof = User.objects.create_user(username='prof-rv', email='prof-rv@example.test', role='teacher')
        session = SessionStore()          # avant Playwright : pas d'accès à la base pendant le navigateur
        session['user_id'] = prof.pk
        session.save()
        self.session_prof = session.session_key
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(
            executable_path=os.environ.get('CHROMIUM_EXECUTABLE') or shutil.which('chromium'),
            headless=True, args=['--no-sandbox'])

    def tearDown(self):
        self.browser.close()
        self.playwright.stop()
        super().tearDown()

    def ouvrir(self, chemin, micro=True, largeur=1280, hauteur=800, session=None):
        context = self.browser.new_context(viewport={'width': largeur, 'height': hauteur})
        context.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': session or self.session,
                              'url': self.live_server_url}])
        context.add_init_script(MICRO if micro else SANS_MICRO)
        page = context.new_page()
        page.route('https://fonts.googleapis.com/**', lambda route: route.abort())
        page.route('https://fonts.gstatic.com/**', lambda route: route.abort())
        erreurs = []
        page.on('pageerror', lambda exc: erreurs.append(str(exc)))
        page.goto(self.live_server_url + chemin)
        return page, erreurs

    def parler(self, page, texte):
        page.locator('#rvFab').click()
        page.wait_for_function('window.__ecoute === true')
        expect(page.locator('#rvEtat')).to_have_text('Je vous écoute…')
        page.evaluate('([t]) => window.__dire(t, false)', [texte[:6]])
        page.evaluate('([t]) => window.__dire(t, true)', [texte])

    def test_dictee_ouvre_directement_la_lecon(self):
        page, erreurs = self.ouvrir(reverse('education:about'))
        expect(page.locator('#rvFab .bi-mic-fill')).to_be_visible()
        self.parler(page, 'les suites numériques')
        expect(page.locator('#rvChamp')).to_have_value('les suites numériques')
        expect(page.locator('#rvDirect')).to_be_visible()
        expect(page.locator('#rvDirectTexte')).to_contain_text('Les suites numériques')
        page.wait_for_url('**' + reverse('education:lesson_detail', args=[self.lesson.pk]))
        self.assertEqual(erreurs, [])

    def test_annuler_garde_la_liste_et_echap_ferme(self):
        page, erreurs = self.ouvrir(reverse('education:about'))
        self.parler(page, 'messagerie')
        expect(page.locator('#rvDirect')).to_be_visible()
        page.locator('#rvAnnuler').click()
        expect(page.locator('#rvDirect')).to_be_hidden()
        page.wait_for_timeout(1500)
        self.assertIn(reverse('education:about'), page.url)          # resté sur la page
        expect(page.locator('.rv-item')).to_have_count(1)
        page.keyboard.press('Escape')
        expect(page.locator('#rvPanel')).to_be_hidden()
        expect(page.locator('#rvFab')).to_be_visible()
        self.assertEqual(erreurs, [])

    def test_micro_refuse_passe_au_clavier(self):
        page, _ = self.ouvrir(reverse('education:about'))
        page.locator('#rvFab').click()
        page.wait_for_function('window.__ecoute === true')
        page.evaluate('window.__refuser()')
        expect(page.locator('#rvEtat')).to_contain_text('Micro refusé')
        expect(page.locator('#rvMicro')).to_be_hidden()
        expect(page.locator('#rvChamp')).to_be_focused()

    def test_sans_reconnaissance_vocale_clavier_et_entree(self):
        page, erreurs = self.ouvrir(reverse('education:about'), micro=False)
        expect(page.locator('#rvFab .bi-search')).to_be_visible()
        page.keyboard.press('Control+k')
        expect(page.locator('#rvChamp')).to_be_focused()
        expect(page.locator('#rvMicro')).to_be_hidden()
        page.keyboard.type('suites numeriques')
        expect(page.locator('.rv-item').first).to_contain_text('Les suites numériques')
        expect(page.locator('#rvDirect')).to_be_hidden()      # au clavier, pas d'ouverture automatique
        page.keyboard.press('Enter')
        page.wait_for_url('**' + reverse('education:lesson_detail', args=[self.lesson.pk]))
        self.assertEqual(erreurs, [])

    def test_paragraphe_ouvert_et_mis_en_evidence(self):
        page, erreurs = self.ouvrir(reverse('education:about'), micro=False)
        page.keyboard.press('/')
        page.keyboard.type('suite arithmetique')
        lien = page.locator('.rv-item .rv-lien[href*="/cours/#s"]').first
        expect(lien).to_be_visible()
        cle = re.search(r'#(s\d+(?:-[bt]\d+)?)$', lien.get_attribute('href')).group(1)
        lien.click()
        page.wait_for_selector('html.pagine-pret', state='attached', timeout=30000)
        expect(page.locator('.feuille.visible .cible-recherche')).to_be_visible()
        cible = page.locator(f'.feuille.visible :is([data-cle="{cle}"], [data-ancre="{cle}"])').first
        expect(cible).to_have_class(re.compile('cible-recherche'))
        expect(cible).to_be_in_viewport()
        expect(cible).not_to_have_class(re.compile('cible-recherche'), timeout=6000)   # le halo s'efface
        self.assertEqual(erreurs, [])
        # Un bloc (« s2-b3 ») et un sous-titre (« s1-t1 ») : la bonne page, l'élément mis en évidence.
        for cle in ('s2-b3', 's1-t1'):
            page.goto(self.live_server_url + reverse('education:lesson_course_html', args=[self.lesson.pk])
                      + '#' + cle)
            page.wait_for_selector('html.pagine-pret', state='attached', timeout=30000)
            cible = page.locator(f'.feuille.visible :is([data-cle="{cle}"], [data-ancre="{cle}"])').first
            expect(cible).to_have_class(re.compile('cible-recherche'))
            expect(cible).to_be_in_viewport()

    def test_telephone_au_dessus_de_la_barre_et_absent_du_chat(self):
        page, _ = self.ouvrir(reverse('accounts:dashboard'), largeur=390, hauteur=780)
        fab = page.locator('#rvFab').bounding_box()
        barre = page.locator('.bottom-nav').bounding_box()
        self.assertLessEqual(fab['y'] + fab['height'], barre['y'])
        self.parler(page, 'produit')
        panneau = page.locator('.rv-panneau').bounding_box()
        self.assertLessEqual(panneau['x'] + panneau['width'], 390)
        largeur = page.evaluate('document.documentElement.scrollWidth')
        self.assertLessEqual(largeur, 390)

    def test_professeur_cahier_de_textes_en_arabe(self):
        page, erreurs = self.ouvrir(reverse('education:about'), session=self.session_prof)
        page.locator('#rvFab').click()
        page.wait_for_function('window.__ecoute === true')
        page.locator('#rvLangue').click()
        expect(page.locator('#rvLangue')).to_have_text('ع')
        page.wait_for_function('window.__reco && window.__reco.lang === "ar-MA"')
        page.wait_for_function('window.__ecoute === true')
        page.evaluate('() => window.__dire("افتح دفتر النصوص", true)')
        page.wait_for_url(lambda url: '/cahier-de-textes/' in url)
        self.assertEqual(erreurs, [])
