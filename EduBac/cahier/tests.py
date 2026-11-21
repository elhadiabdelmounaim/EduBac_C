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
        page = self.client.get(reverse('cahier:index')).content.decode()
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
        page = self.client.get(reverse('cahier:index')).content.decode()
        from .views import duree
        cumul = minutes['s1-b1'] + minutes['s1-b2'] + minutes['s1-b3']
        self.assertIn(f'Durée prévue : {duree(minutes["s1-b2"] + minutes["s1-b3"])}', page)
        self.assertIn(f'Leçon : {duree(cumul)} / 13 h', page)
        self.assertIn(f'Leçon : {duree(minutes["s1-b1"] + minutes["s1-b2"])} / 13 h', page)   # séance du 20

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
