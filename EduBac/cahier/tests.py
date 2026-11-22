"""Cahier de textes : plan du cours, enregistrement depuis le panneau « Séance », consultation."""
import datetime
import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from classrooms.models import Classroom
from education.models import Course, Lesson

from .models import Seance, SeanceElement
from .rubriques import elements, plan_de_lecon

User = get_user_model()


class CahierBase(TestCase):
    def setUp(self):
        course = Course.objects.create(name='Mathématiques', niveau='1ere_bac_sc')
        self.lesson = Lesson.objects.create(
            title='Le produit scalaire dans le plan', content='', course=course, order=4)
        self.sans_html = Lesson.objects.create(title='Les suites', content='', course=course, order=5)
        self.prof = User.objects.create_user(username='prof', email='prof@example.test', role='teacher')
        self.autre_prof = User.objects.create_user(username='prof2', email='prof2@example.test', role='teacher')
        self.eleve = User.objects.create_user(username='eleve', email='eleve@example.test', role='student')
        self.classe = Classroom.objects.create(name='1BAC SE 2', niveau='1ere_bac_sc', teacher=self.prof)
        self.autre_classe = Classroom.objects.create(name='1BAC SE 5', niveau='1ere_bac_sc', teacher=self.autre_prof)
        self.etat_url = reverse('cahier:etat', args=[self.lesson.pk])
        self.save_url = reverse('cahier:enregistrer', args=[self.lesson.pk])

    def login_as(self, user):
        session = self.client.session
        session['user_id'] = user.pk
        session.save()

    def post(self, data):
        return self.client.post(self.save_url, json.dumps(data), content_type='application/json')


class CahierTests(CahierBase):

    # ---------- Plan du cours ----------
    def test_plan_has_parts_subtitles_and_blocks(self):
        plan = plan_de_lecon(self.lesson)
        self.assertEqual(len(plan), 9)
        self.assertEqual(plan[0]['titre'], 'I. Étude analytique du produit scalaire')
        sous = plan[0]['enfants'][0]
        self.assertEqual(sous['type'], 'titre')
        self.assertEqual(sous['titre'], 'I.1 Expression analytique du produit scalaire')
        self.assertEqual([b['titre'] for b in sous['enfants']], ['Proposition', 'Remarque', 'Exemples', 'Applications'])
        # Partie sans sous-titre : ses blocs sont directement dessous.
        self.assertEqual(plan[1]['enfants'][0]['type'], 'bloc')
        feuilles = elements(plan)
        self.assertEqual(len(feuilles), 50)
        self.assertEqual(len({f['key'] for f in feuilles}), 50)
        self.assertEqual(feuilles[0]['sous_titre'], 'I.1 Expression analytique du produit scalaire')
        self.assertIsNone(plan_de_lecon(self.sans_html))

    # ---------- Accès ----------
    def test_only_teachers_can_use_the_journal(self):
        self.assertEqual(self.client.get(self.etat_url).status_code, 403)
        self.assertEqual(self.post({}).status_code, 403)
        self.login_as(self.eleve)
        self.assertEqual(self.client.get(self.etat_url).status_code, 403)
        self.assertEqual(self.post({'classe': self.classe.pk, 'date': '2026-11-21', 'cles': ['s1-b1']}).status_code, 403)
        self.assertRedirects(self.client.get(reverse('cahier:index')), reverse('education:home'),
                             fetch_redirect_response=False)
        self.assertFalse(Seance.objects.exists())

    def test_course_page_shows_panel_to_teachers_only(self):
        url = reverse('education:lesson_course_html', args=[self.lesson.pk])
        self.login_as(self.eleve)
        page = self.client.get(url).content.decode()
        self.assertNotIn('seancePanneau', page)
        self.assertNotIn('cahier-seance.js', page)
        self.login_as(self.prof)
        page = self.client.get(url).content.decode()
        self.assertIn('id="seancePanneau"', page)
        self.assertIn(self.save_url, page)

    # ---------- Enregistrement ----------
    def test_state_lists_own_classes_and_plan(self):
        self.login_as(self.prof)
        data = self.client.get(self.etat_url).json()
        self.assertEqual([c['nom'] for c in data['classes']], ['1BAC SE 2'])
        self.assertEqual(len(data['plan']), 9)
        self.assertEqual(self.client.get(reverse('cahier:etat', args=[self.sans_html.pk])).status_code, 404)

    def test_save_with_date_class_and_titles(self):
        self.login_as(self.prof)
        r = self.post({'classe': self.classe.pk, 'date': '2026-11-21', 'cles': ['s1-b3', 's1-b1', 's1-b2']})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()['ok'])
        seance = Seance.objects.get()
        self.assertEqual((seance.teacher, seance.classroom, seance.lesson), (self.prof, self.classe, self.lesson))
        self.assertEqual(seance.date, datetime.date(2026, 11, 21))
        titres = list(seance.elements.values_list('title', 'partie', 'sous_titre'))
        self.assertEqual(titres[0], ('Proposition', 'I. Étude analytique du produit scalaire',
                                     'I.1 Expression analytique du produit scalaire'))
        self.assertEqual([t[0] for t in titres], ['Proposition', 'Remarque', 'Exemples'])   # ordre du cours

    def test_saving_same_day_again_updates_without_duplicate(self):
        self.login_as(self.prof)
        self.post({'classe': self.classe.pk, 'date': '2026-11-21', 'cles': ['s1-b1']})
        r = self.post({'classe': self.classe.pk, 'date': '2026-11-21', 'cles': ['s1-b1', 's1-b2', 's1-b2']})
        self.assertFalse(r.json()['cree'])
        self.assertEqual(Seance.objects.count(), 1)
        self.assertEqual(SeanceElement.objects.count(), 2)
        # Un autre jour : nouvelle séance, la précédente n'est pas touchée.
        self.post({'classe': self.classe.pk, 'date': '2026-11-24', 'cles': ['s2-b1']})
        self.assertEqual(Seance.objects.count(), 2)
        self.assertEqual(Seance.objects.get(date='2026-11-21').elements.count(), 2)
        # L'état d'un jour donne la sélection enregistrée et ce qui a été vu les autres jours.
        data = self.client.get(self.etat_url, {'classe': self.classe.pk, 'date': '2026-11-24'}).json()
        self.assertTrue(data['existe'])
        self.assertEqual(data['selection'], ['s2-b1'])
        self.assertEqual(data['deja'], {'s1-b1': '21/11', 's1-b2': '21/11'})

    def test_invalid_requests_are_refused(self):
        self.login_as(self.prof)
        base = {'classe': self.classe.pk, 'date': '2026-11-21', 'cles': ['s1-b1']}
        for changement in ({'cles': []}, {'cles': ['s99-b1']}, {'date': '21/11/2026'}, {'classe': ''},
                           {'classe': self.autre_classe.pk}):
            r = self.post(dict(base, **changement))
            self.assertEqual(r.status_code, 400, changement)
            self.assertFalse(r.json()['ok'])
        self.assertIn('Cochez', self.post(dict(base, cles=[])).json()['message'])
        self.assertFalse(Seance.objects.exists())

    def test_csrf_is_required(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=True)
        session = client.session
        session['user_id'] = self.prof.pk
        session.save()
        r = client.post(self.save_url, json.dumps({'classe': self.classe.pk, 'date': '2026-11-21', 'cles': ['s1-b1']}),
                        content_type='application/json')
        self.assertEqual(r.status_code, 403)

    # ---------- Consultation ----------
    def test_journal_lists_date_class_and_titles(self):
        self.login_as(self.prof)
        self.post({'classe': self.classe.pk, 'date': '2026-11-21', 'cles': ['s1-b1', 's1-b4', 's1-b5']})
        Seance.objects.create(teacher=self.autre_prof, classroom=self.autre_classe, lesson=self.lesson,
                              date=datetime.date(2026, 11, 20))
        page = self.client.get(reverse('cahier:niveau', args=['1ere_bac_sc'])).content.decode()
        self.assertIn('Samedi 21 novembre 2026', page)
        self.assertIn('1BAC SE 2', page)
        self.assertIn('I. Étude analytique du produit scalaire', page)
        self.assertIn('I.1 Expression analytique du produit scalaire', page)
        self.assertIn('I.2 Norme d', page)
        self.assertNotIn('1BAC SE 5', page)          # classe d'un autre enseignant
        self.assertNotIn('20 novembre 2026', page)    # séance d'un autre enseignant

    def test_delete_only_own_session(self):
        mien = Seance.objects.create(teacher=self.prof, classroom=self.classe, lesson=self.lesson,
                                     date=datetime.date(2026, 11, 21))
        autre = Seance.objects.create(teacher=self.autre_prof, classroom=self.autre_classe, lesson=self.lesson,
                                      date=datetime.date(2026, 11, 21))
        self.login_as(self.prof)
        self.assertEqual(self.client.post(reverse('cahier:supprimer', args=[autre.pk])).status_code, 404)
        self.client.post(reverse('cahier:supprimer', args=[mien.pk]))
        self.assertEqual(list(Seance.objects.all()), [autre])


class MinutageTests(CahierBase):
    """Répartition horaire : 13 h pour le produit scalaire, réparties entre les blocs."""

    def test_lesson_hours_come_from_the_reference_timetable(self):
        from education.repartition import repartition_de_lecon
        rep = repartition_de_lecon(self.lesson)
        self.assertEqual((rep['heures'], rep['semaines'], rep['annee']), (13, 'S8 – S11', '2026-2027'))
        self.assertEqual(repartition_de_lecon(self.sans_html)['heures'], 7)     # leçon 05 : suites

    def test_minutes_cover_the_lesson_hours(self):
        plan = plan_de_lecon(self.lesson)
        feuilles = elements(plan)
        self.assertEqual(sum(f['minutes'] for f in feuilles), 13 * 60)
        self.assertEqual(sum(p['minutes'] for p in plan), 13 * 60)
        self.assertTrue(all(f['minutes'] >= 5 and f['minutes'] % 5 == 0 for f in feuilles))
        # Une partie vaut la somme de ses sous-titres et blocs.
        un = plan[0]
        self.assertEqual(un['minutes'], sum(e['minutes'] for e in un['enfants']))
        # À volume égal, une application compte plus qu'une proposition.
        sous = un['enfants'][0]['enfants']
        self.assertGreater(sous[3]['minutes'], sous[0]['minutes'])

    def test_fixed_minutes_are_kept(self):
        from .rubriques import minuter
        plan = [{'key': 's1', 'type': 'partie', 'titre': 'I', 'enfants': [
            {'key': 's1-b1', 'type': 'bloc', 'titre': 'Définition', 'genre': 'def', 'taille': 300, 'figures': 0, 'fixe': '30'},
            {'key': 's1-b2', 'type': 'bloc', 'titre': 'Exemples', 'genre': 'ex', 'taille': 300, 'figures': 0},
            {'key': 's1-b3', 'type': 'bloc', 'titre': 'Applications', 'genre': 'app', 'taille': 300, 'figures': 0},
        ]}]
        minuter(plan, 100)
        b = plan[0]['enfants']
        self.assertEqual(b[0]['minutes'], 30)
        self.assertEqual(b[1]['minutes'] + b[2]['minutes'], 70)
        self.assertEqual(plan[0]['minutes'], 100)

    def test_saved_minutes_duration_and_progress(self):
        self.login_as(self.prof)
        data = self.client.get(self.etat_url).json()
        self.assertEqual(data['repartition']['heures'], 13)
        minutes = {e['key']: e['minutes'] for e in elements(data['plan'])}
        self.post({'classe': self.classe.pk, 'date': '2026-11-20', 'cles': ['s1-b1', 's1-b2']})
        self.post({'classe': self.classe.pk, 'date': '2026-11-21', 'cles': ['s1-b2', 's1-b3']})
        seance = Seance.objects.get(date='2026-11-21')
        self.assertEqual([e.minutes for e in seance.elements.all()], [minutes['s1-b2'], minutes['s1-b3']])
        page = self.client.get(reverse('cahier:niveau', args=['1ere_bac_sc'])).content.decode()
        from .views import duree
        # Temps réellement passé : somme des deux séances (s1-b2, revu le 21, compte deux fois).
        cumul = (minutes['s1-b1'] + minutes['s1-b2']) + (minutes['s1-b2'] + minutes['s1-b3'])
        # Sans durée saisie, la durée réalisée vaut la durée prévue des éléments cochés.
        self.assertIn(f'Durée réalisée : <strong>{duree(minutes["s1-b2"] + minutes["s1-b3"])}</strong>', page)
        self.assertIn(f'Leçon : <strong>{duree(cumul)}</strong> / 13 h', page)
        self.assertIn(f'Leçon : <strong>{duree(minutes["s1-b1"] + minutes["s1-b2"])}</strong> / 13 h', page)   # séance du 20

    def test_duration_format(self):
        from .views import duree
        self.assertEqual([duree(40), duree(60), duree(95), duree(780)], ['40 min', '1 h', '1 h 35', '13 h'])

    def test_timer_data_on_course_page_for_teachers_only(self):
        url = reverse('education:lesson_course_html', args=[self.lesson.pk])
        self.login_as(self.eleve)
        self.assertNotIn('cours-minutage', self.client.get(url).content.decode())
        self.login_as(self.prof)
        page = self.client.get(url).content.decode()
        self.assertIn('id="cours-minutage"', page)
        self.assertIn('id="minuteur"', page)


class JournalNiveauTests(CahierBase):
    """Cartes des niveaux, séances d'un niveau, recherche, PDF (une, sélection, toutes), droits."""

    def setUp(self):
        super().setUp()
        self.directeur = User.objects.create_user(username='dir', email='dir@example.test', is_staff=True)
        tc = Course.objects.create(name='Maths TC', niveau='tronc_commun')
        self.lecon_tc = Lesson.objects.create(title='Les ensembles', content='', course=tc, order=1)
        self.classe_tc = Classroom.objects.create(name='TC 3', niveau='tronc_commun', teacher=self.prof)
        self.s1 = self.seance(self.prof, self.classe, '2026-11-02', [('Définition', 'I. Partie', ''),
                                                                     ('Application 1', 'I. Partie', '')])
        self.s2 = self.seance(self.prof, self.classe, '2026-11-09', [('Exemples', 'II. Cercle', 'II.1 Équation')],
                              observations='Devoir n° 2 donné.')
        self.s3 = self.seance(self.autre_prof, self.autre_classe, '2026-11-05', [('Propriété', 'I. Partie', '')])
        self.s4 = self.seance(self.prof, self.classe_tc, '2026-11-03', [('Définition', 'I. Ensembles', '')],
                              lecon=self.lecon_tc)
        self.url = reverse('cahier:niveau', args=['1ere_bac_sc'])
        self.pdf_url = reverse('cahier:niveau_pdf', args=['1ere_bac_sc'])

    def seance(self, prof, classe, jour, elements_, observations='', lecon=None):
        s = Seance.objects.create(teacher=prof, classroom=classe, lesson=lecon or self.lesson,
                                  date=datetime.date.fromisoformat(jour), observations=observations)
        for k, (titre, partie, sous_titre) in enumerate(elements_):
            SeanceElement.objects.create(seance=s, key=f's1-b{k + 1}', title=titre, partie=partie,
                                         sous_titre=sous_titre, order=k, minutes=20)
        return s

    def texte_pdf(self, response):
        import io
        from pypdf import PdfReader
        self.assertEqual(response['Content-Type'], 'application/pdf')
        lecteur = PdfReader(io.BytesIO(b''.join(response.streaming_content) if response.streaming else response.content))
        return lecteur, '\n'.join(page.extract_text() for page in lecteur.pages)

    def test_level_cards_count_own_sessions(self):
        self.login_as(self.prof)
        page = self.client.get(reverse('cahier:index')).content.decode()
        self.assertIn('1ère Bac Sciences', page)
        self.assertIn('Tronc Commun', page)
        self.assertNotIn('2ème Bac SVT', page)        # aucun cours de ce niveau
        self.assertIn(self.url, page)
        self.assertIn('<strong>2</strong> séances', page)
        self.assertIn('<strong>1</strong> séance<', page)
        self.assertIn('3 séances au total', page)

    def test_director_sees_every_teacher(self):
        self.login_as(self.directeur)
        self.assertIn('<strong>3</strong> séances', self.client.get(reverse('cahier:index')).content.decode())
        page = self.client.get(self.url).content.decode()
        self.assertIn('1BAC SE 5', page)
        self.assertIn('prof2', page)                  # nom de l'enseignant affiché
        self.assertNotIn('cahier:observations', page)
        self.assertNotIn(reverse('cahier:observations', args=[self.s3.pk]), page)   # pas d'écriture chez les autres
        self.assertEqual(self.client.get(reverse('cahier:seance_pdf', args=[self.s3.pk])).status_code, 200)

    def test_level_page_lists_numbered_sessions_newest_first(self):
        self.login_as(self.prof)
        page = self.client.get(self.url).content.decode()
        self.assertLess(page.index('id="seance-%d"' % self.s2.pk), page.index('id="seance-%d"' % self.s1.pk))
        self.assertIn('Séance n° 1', page)
        self.assertIn('Séance n° 2', page)
        self.assertIn('Lundi 9 novembre 2026', page)
        self.assertIn('Le produit scalaire dans le plan', page)
        self.assertIn('II.1 Équation', page)
        self.assertIn('Devoir n° 2 donné.', page)
        self.assertIn('Activités et exercices effectués', page)
        self.assertNotIn('1BAC SE 5', page)          # séance d'un autre enseignant
        self.assertNotIn('Les ensembles', page)       # autre niveau
        self.assertEqual(self.client.get(reverse('cahier:niveau', args=['inconnu'])).status_code, 404)

    def test_search_and_period_filters(self):
        self.login_as(self.prof)
        page = self.client.get(self.url, {'q': 'devoir'}).content.decode()
        self.assertIn('id="seance-%d"' % self.s2.pk, page)
        self.assertNotIn('id="seance-%d"' % self.s1.pk, page)
        page = self.client.get(self.url, {'q': 'Application'}).content.decode()
        self.assertIn('id="seance-%d"' % self.s1.pk, page)
        self.assertNotIn('id="seance-%d"' % self.s2.pk, page)
        page = self.client.get(self.url, {'du': '2026-11-05', 'au': '2026-11-30'}).content.decode()
        self.assertIn('id="seance-%d"' % self.s2.pk, page)
        self.assertNotIn('id="seance-%d"' % self.s1.pk, page)
        self.assertIn('Séance n° 2', page)           # le numéro ne dépend pas du filtre

    def test_pagination(self):
        self.login_as(self.prof)
        for k in range(20):
            self.seance(self.prof, self.classe, (datetime.date(2026, 9, 1) + datetime.timedelta(days=k)).isoformat(),
                        [('Exemples', 'I. Partie', '')])
        page = self.client.get(self.url).content.decode()
        self.assertEqual(page.count('class="cahier-seance"'), 15)
        self.assertIn('Page 1 / 2', page)
        page2 = self.client.get(self.url, {'page': 2, 'q': 'Exemples'}).content.decode()
        self.assertIn('Page 2 / 2', page2)

    def test_single_session_pdf(self):
        self.login_as(self.prof)
        response = self.client.get(reverse('cahier:seance_pdf', args=[self.s2.pk]))
        self.assertIn('attachment', response['Content-Disposition'])
        _, texte = self.texte_pdf(response)
        for attendu in ('EduBac', '1ère Bac Sciences', 'Lundi 9 novembre 2026', 'Séance n° 2',
                        'Le produit scalaire dans le plan', 'II. Cercle', 'II.1 Équation', 'Exemples',
                        'Observations', 'Devoir n° 2 donné.'):
            self.assertIn(attendu, texte)
        # Séance d'un autre enseignant : introuvable.
        self.assertEqual(self.client.get(reverse('cahier:seance_pdf', args=[self.s3.pk])).status_code, 404)

    def test_selection_pdf_in_chronological_order(self):
        self.login_as(self.prof)
        response = self.client.get(self.pdf_url + f'?ids={self.s2.pk}&ids={self.s1.pk}&ids={self.s3.pk}')
        _, texte = self.texte_pdf(response)
        self.assertLess(texte.index('2 novembre 2026'), texte.index('9 novembre 2026'))
        self.assertNotIn('Sommaire', texte)
        self.assertNotIn('1BAC SE 5', texte)         # la séance d'un autre est ignorée
        self.assertEqual(self.client.get(self.pdf_url + f'?ids={self.s3.pk}').status_code, 404)

    def test_full_level_pdf_with_cover_and_summary(self):
        self.login_as(self.prof)
        for k in range(60):
            self.seance(self.prof, self.classe, (datetime.date(2026, 9, 1) + datetime.timedelta(days=k)).isoformat(),
                        [('Exemples', 'I. Partie', ''), ('Application 2', 'I. Partie', '')])
        response = self.client.get(self.pdf_url)
        self.assertIn('cahier-de-textes-1ere_bac_sc-complet.pdf', response['Content-Disposition'])
        lecteur, texte = self.texte_pdf(response)
        self.assertGreater(len(lecteur.pages), 5)
        premiere = lecteur.pages[0].extract_text()
        self.assertIn('Cahier de textes', premiere)
        self.assertIn('1ère Bac Sciences', premiere)
        self.assertIn('Période : du', premiere)
        self.assertIn('62 séances', premiere)
        self.assertIn('Sommaire', texte)
        self.assertNotIn('Les ensembles', texte)

    def test_observations_only_by_owner(self):
        self.login_as(self.autre_prof)
        url = reverse('cahier:observations', args=[self.s1.pk])
        self.assertEqual(self.client.post(url, {'observations': 'piraté'}).status_code, 404)
        self.login_as(self.prof)
        self.assertRedirects(self.client.post(url, {'observations': '  Bonne participation.  '}),
                             self.url + f'#seance-{self.s1.pk}', fetch_redirect_response=False)
        self.s1.refresh_from_db()
        self.assertEqual(self.s1.observations, 'Bonne participation.')

    def test_panel_saves_and_returns_observations(self):
        self.login_as(self.prof)
        r = self.post({'classe': self.classe.pk, 'date': '2026-11-21', 'cles': ['s1-b1'],
                       'observations': 'Contrôle annoncé.'}).json()
        self.assertTrue(r['ok'])
        self.assertIn(self.url, r['url'])
        data = self.client.get(self.etat_url, {'classe': self.classe.pk, 'date': '2026-11-21'}).json()
        self.assertEqual(data['observations'], 'Contrôle annoncé.')
        # Sans le champ, les observations existantes sont conservées.
        self.post({'classe': self.classe.pk, 'date': '2026-11-21', 'cles': ['s1-b2']})
        self.assertEqual(Seance.objects.get(date='2026-11-21').observations, 'Contrôle annoncé.')

    def test_old_class_links_redirect_to_level(self):
        self.login_as(self.prof)
        self.assertRedirects(self.client.get(reverse('cahier:index'), {'classe': self.classe.pk}),
                             self.url + f'?classe={self.classe.pk}', fetch_redirect_response=False)

    def test_students_cannot_access(self):
        self.login_as(self.eleve)
        for url in (self.url, self.pdf_url, reverse('cahier:seance_pdf', args=[self.s1.pk])):
            self.assertRedirects(self.client.get(url), reverse('education:home'), fetch_redirect_response=False)


class SuiviTempsTests(CahierBase):
    """Durée réalisée des séances, déduite de la durée prévue de la leçon (sans double déduction)."""

    def setUp(self):
        super().setUp()
        self.lesson.duree_prevue_minutes = 360           # 6 h, prioritaire sur la répartition (13 h)
        self.lesson.save()
        self.login_as(self.prof)

    def seance(self, jour, minutes, classe=None, cles=('s1-b1',)):
        r = self.post({'classe': (classe or self.classe).pk, 'date': jour, 'cles': list(cles), 'duree': minutes})
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def test_example_from_the_specification(self):
        self.seance('2026-11-02', 60)
        self.seance('2026-11-09', 90)
        suivi = self.seance('2026-11-16', 60)['suivi']
        self.assertEqual((suivi['prevu'], suivi['realise'], suivi['restant']), (360, 210, 150))
        self.assertEqual((suivi['prevu_texte'], suivi['realise_texte'], suivi['restant_texte']), ('6 h', '3 h 30', '2 h 30'))
        self.assertEqual((suivi['pourcent'], suivi['reste_pourcent']), (58.33, 41.67))
        self.assertEqual((suivi['pourcent_texte'], suivi['reste_pourcent_texte']), ('58,33', '41,67'))
        # Même bilan à la réouverture du panneau et sur la page du niveau.
        etat = self.client.get(self.etat_url, {'classe': self.classe.pk, 'date': '2026-11-16'}).json()
        self.assertEqual((etat['duree'], etat['suivi']['realise'], etat['prevu_texte']), (60, 210, '6 h'))
        page = self.client.get(reverse('cahier:niveau', args=['1ere_bac_sc'])).content.decode()
        self.assertIn('Progression des leçons', page)
        self.assertIn('<strong>58,33 %</strong> réalisé', page)
        self.assertIn('41,67 % restant', page)
        self.assertIn('<dt>Durée restante</dt><dd>2 h 30</dd>', page)
        self.assertIn('Durée réalisée : <strong>1 h 30</strong>', page)

    def test_saving_again_replaces_the_duration_instead_of_adding_it(self):
        self.seance('2026-11-02', 60)
        self.seance('2026-11-02', 60)
        suivi = self.seance('2026-11-02', 90)['suivi']
        self.assertEqual(Seance.objects.count(), 1)
        self.assertEqual(suivi['realise'], 90)

    def test_edit_and_delete_recompute_the_progress(self):
        self.seance('2026-11-02', 60)
        self.seance('2026-11-09', 90)
        s = Seance.objects.get(date='2026-11-09')
        self.client.post(reverse('cahier:observations', args=[s.pk]), {'duree': '30', 'observations': 'ok'})
        s.refresh_from_db()
        self.assertEqual((s.duree_minutes, s.observations), (30, 'ok'))
        etat = self.client.get(self.etat_url, {'classe': self.classe.pk, 'date': '2026-11-09'}).json()
        self.assertEqual(etat['suivi']['realise'], 90)
        self.client.post(reverse('cahier:supprimer', args=[s.pk]))
        etat = self.client.get(self.etat_url, {'classe': self.classe.pk, 'date': '2026-11-09'}).json()
        self.assertEqual((etat['suivi']['realise'], etat['suivi']['restant']), (60, 300))
        # Observations seules : la durée ne change pas.
        premiere = Seance.objects.get()
        self.client.post(reverse('cahier:observations', args=[premiere.pk]), {'observations': 'devoir'})
        premiere.refresh_from_db()
        self.assertEqual(premiere.duree_minutes, 60)

    def test_remaining_time_is_never_negative(self):
        for k in range(4):
            suivi = self.seance(f'2026-11-0{k + 1}', 120)['suivi']
        self.assertEqual((suivi['realise'], suivi['restant'], suivi['pourcent'], suivi['reste_pourcent']), (480, 0, 100, 0))
        self.assertEqual(suivi['depassement_texte'], '2 h')

    def test_invalid_durations_are_refused(self):
        for valeur in (0, 481, 'abc', -5):
            r = self.post({'classe': self.classe.pk, 'date': '2026-11-02', 'cles': ['s1-b1'], 'duree': valeur})
            self.assertEqual(r.status_code, 400, valeur)
        self.assertFalse(Seance.objects.exists())
        self.seance('2026-11-02', 60)
        s = Seance.objects.get()
        self.client.post(reverse('cahier:observations', args=[s.pk]), {'duree': '0'})
        s.refresh_from_db()
        self.assertEqual(s.duree_minutes, 60)

    def test_each_class_and_each_lesson_has_its_own_progress(self):
        autre = Classroom.objects.create(name='1BAC SE 3', niveau='1ere_bac_sc', teacher=self.prof)
        self.seance('2026-11-02', 120)
        self.assertEqual(self.seance('2026-11-02', 45, classe=autre)['suivi']['realise'], 45)
        etat = self.client.get(self.etat_url, {'classe': self.classe.pk, 'date': '2026-11-03'}).json()
        self.assertEqual(etat['suivi']['realise'], 120)
        # Une autre leçon (autre niveau) n'est pas touchée.
        tc = Lesson.objects.create(title='Les polynômes', content='', order=4,
                                   course=Course.objects.create(name='Maths', niveau='tronc_commun'))
        from .suivi import bilan_lecon
        self.assertEqual(bilan_lecon(Seance.objects.filter(lesson=tc), tc)['realise'], 0)

    def test_old_sessions_without_duration_use_the_planned_minutes(self):
        self.post({'classe': self.classe.pk, 'date': '2026-11-02', 'cles': ['s1-b1', 's1-b2']})
        s = Seance.objects.get()
        self.assertIsNone(s.duree_minutes)
        prevues = sum(e.minutes for e in s.elements.all())
        etat = self.client.get(self.etat_url, {'classe': self.classe.pk, 'date': '2026-11-02'}).json()
        self.assertEqual((etat['duree'], etat['suivi']['realise']), (prevues, prevues))

    def test_planned_duration_falls_back_to_the_timetable(self):
        from education.repartition import duree_prevue_minutes
        self.assertEqual(duree_prevue_minutes(self.lesson), 360)
        self.lesson.duree_prevue_minutes = None
        self.lesson.save()
        self.assertEqual(duree_prevue_minutes(self.lesson), 13 * 60)
        sans = Lesson.objects.create(title='Inconnue', content='', order=40, course=self.lesson.course)
        self.assertIsNone(duree_prevue_minutes(sans))
        from .suivi import bilan
        self.assertEqual(bilan(None, 75), {'realise': 75, 'realise_texte': '1 h 15', 'prevu': None,
                                           'prevu_texte': '', 'connu': False})

    def test_pdf_shows_the_real_duration(self):
        self.seance('2026-11-02', 75)
        s = Seance.objects.get()
        from io import BytesIO
        from pypdf import PdfReader
        r = self.client.get(reverse('cahier:seance_pdf', args=[s.pk]))
        texte = ' '.join(p.extract_text() for p in PdfReader(BytesIO(r.content)).pages)
        self.assertIn('Durée réalisée', texte)
        self.assertIn('1 h 15', texte)
