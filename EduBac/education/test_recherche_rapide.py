"""Recherche rapide (bouton micro flottant) : texte dicté → pages, cours, leçons, paragraphes ;
accents et mots arabes ; leçons verrouillées ; niveau du lecteur en premier ; ouverture directe."""
from django.contrib.sessions.backends.db import SessionStore
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from cahier.models import AccesLecon
from classrooms.models import Classroom, ClassroomMember
from education.models import Course, Lesson
from education.recherche_rapide import mots_de_la_requete, normaliser, score

URL = reverse('education:search_quick')


class OutilsTests(TestCase):
    def test_normalise_accents_casse_et_ponctuation(self):
        self.assertEqual(normaliser('Inégalité  de Cauchy-Schwarz !'), 'inegalite de cauchy schwarz')

    def test_phrase_dictee_sans_mots_vides(self):
        self.assertEqual(mots_de_la_requete('Ouvre-moi la page de la messagerie'), ['messagerie'])
        self.assertEqual(mots_de_la_requete('je veux voir le produit scalaire'), ['produit', 'scalaire'])

    def test_arabe_traduit_en_francais(self):
        self.assertEqual(mots_de_la_requete('افتح الجداء السلمي'), ['produit', 'scalaire'])
        self.assertEqual(mots_de_la_requete('المتتاليات'), ['suites'])

    def test_score(self):
        self.assertEqual(score(['xyz'], 'Les suites numériques'), 0)
        # Mot seulement dans le contexte : pas de résultat ; dans le libellé : oui.
        self.assertEqual(score(['suites'], 'Définition', 'Les suites numériques'), 0)
        self.assertGreater(score(['definition', 'suites'], 'Définition', 'Les suites numériques'), 0)
        # Début de mot : « deriv » trouve « dérivation ».
        self.assertGreater(score(['deriv'], 'La dérivation'), 0)
        self.assertGreater(score(['messagerie'], 'Messagerie'), score(['messagerie'], 'Messagerie des classes'))


class RechercheRapideTests(TestCase):
    def setUp(self):
        self.course = Course.objects.create(name='Mathématiques', niveau='1ere_bac_sc')
        # Leçon 5 de 1ère Bac Sciences : elle a un cours en ligne (paragraphes cherchables).
        self.suites = Lesson.objects.create(title='Les suites numériques', content='', course=self.course, order=5)
        autre = Course.objects.create(name='Mathématiques', niveau='1ere_bac_sm')
        self.suites_sm = Lesson.objects.create(title='Les suites numériques', content='', course=autre, order=40)
        self.prof = User.objects.create_user(username='prof', email='prof@example.test', role='teacher')
        self.eleve = User.objects.create_user(username='eleve', email='eleve@example.test', role='student')
        self.classe = Classroom.objects.create(name='1BAC A', niveau='1ere_bac_sc', teacher=self.prof)
        ClassroomMember.objects.create(classroom=self.classe, user=self.eleve)

    def connecter(self, user):
        session = SessionStore()
        session['user_id'] = user.pk
        session.save()
        self.client.cookies['sessionid'] = session.session_key

    def chercher(self, q):
        reponse = self.client.get(URL, {'q': q})
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse['Cache-Control'], 'private, no-store')
        return reponse.json()

    def test_requete_vide_ou_trop_courte(self):
        self.assertEqual(self.chercher('')['resultats'], [])
        self.assertEqual(self.chercher('a')['resultats'], [])
        self.assertIsNone(self.chercher('la page de')['direct'])

    def test_visiteur_pages_publiques_et_lecons_verrouillees(self):
        donnees = self.chercher('connexion')
        self.assertEqual(donnees['direct'], reverse('accounts:login'))
        self.assertEqual(self.chercher('cahier de textes')['resultats'], [])   # page du professeur
        donnees = self.chercher('suites numériques')
        lecons = [r for r in donnees['resultats'] if r['type'] == 'lecon']
        self.assertEqual(len(lecons), 2)
        self.assertTrue(all(r['verrou'] for r in lecons))
        self.assertIsNone(donnees['direct'])     # jamais d'ouverture directe vers une leçon verrouillée

    def test_eleve_messagerie_directe_et_pas_de_pages_professeur(self):
        self.connecter(self.eleve)
        donnees = self.chercher('ouvre la messagerie')
        self.assertEqual(donnees['resultats'][0]['type'], 'page')
        self.assertEqual(donnees['direct'], reverse('chat:home'))
        self.assertEqual([r for r in self.chercher('cahier de textes')['resultats'] if r['type'] == 'page'], [])

    def test_professeur_voit_ses_pages(self):
        self.connecter(self.prof)
        self.assertEqual(self.chercher('cahier de textes')['direct'], reverse('cahier:index'))
        self.assertEqual(self.chercher('افتح دفتر النصوص')['direct'], reverse('cahier:index'))

    def test_niveau_de_l_eleve_en_premier_et_ouverture_directe(self):
        AccesLecon.objects.create(classroom=self.classe, lesson=self.suites, decision=AccesLecon.OUVERT)
        self.connecter(self.eleve)
        donnees = self.chercher('les suites numériques')
        premier = donnees['resultats'][0]
        self.assertEqual(premier['url'], reverse('education:lesson_detail', args=[self.suites.pk]))
        self.assertFalse(premier['verrou'])
        self.assertEqual(donnees['direct'], premier['url'])
        # En arabe aussi.
        self.assertEqual(self.chercher('المتتاليات')['resultats'][0]['url'], premier['url'])

    def test_eleve_leçon_non_ouverte_reste_verrouillee(self):
        self.connecter(self.eleve)
        donnees = self.chercher('les suites numériques')
        self.assertTrue(donnees['resultats'][0]['verrou'])
        self.assertIsNone(donnees['direct'])

    def test_paragraphes_du_cours_en_ligne(self):
        self.connecter(self.prof)
        paragraphes = [r for r in self.chercher('suite arithmétique')['resultats'] if r['type'] == 'paragraphe']
        self.assertTrue(paragraphes)
        base = reverse('education:lesson_course_html', args=[self.suites.pk])
        for r in paragraphes:
            self.assertRegex(r['url'], '^' + base + r'#s\d+(-[bt]\d+)?$')
            self.assertIn('Les suites numériques', r['detail'])

    def test_mot_dans_le_texte_d_un_bloc_avec_extrait(self):
        AccesLecon.objects.create(classroom=self.classe, lesson=self.suites, decision=AccesLecon.OUVERT)
        self.connecter(self.eleve)
        trouves = [r for r in self.chercher('inégalités strictes')['resultats'] if r.get('extrait')]
        self.assertTrue(trouves)
        self.assertIn('inégalités strictes', trouves[0]['extrait'])
        self.assertRegex(trouves[0]['url'], r'#s\d+-b\d+$')

    def test_pas_d_extrait_pour_une_lecon_verrouillee(self):
        self.connecter(self.eleve)          # leçon pas encore ouverte à sa classe
        self.assertFalse([r for r in self.chercher('inégalités strictes')['resultats'] if r.get('extrait')])
        self.client.cookies.clear()          # visiteur
        self.assertFalse([r for r in self.chercher('inégalités strictes')['resultats'] if r.get('extrait')])

    def test_resultats_limites_et_peu_de_requetes(self):
        self.connecter(self.prof)
        self.chercher('suite')       # premier passage : lecture du plan du cours
        with self.assertNumQueries(5):      # session, utilisateur, classes, cours, leçons
            donnees = self.chercher('suite')
        self.assertLessEqual(len([r for r in donnees['resultats'] if r['type'] == 'paragraphe']), 8)

    def test_bouton_micro_sur_les_pages_sauf_salons(self):
        reponse = self.client.get(reverse('education:about'))
        self.assertContains(reponse, 'id="rvFab"')
        self.assertContains(reponse, reverse('education:search_quick'))
        self.connecter(self.eleve)
        reponse = self.client.get(reverse('chat:home'))
        if reponse.status_code == 200:
            self.assertContains(reponse, 'id="rvFab"')
