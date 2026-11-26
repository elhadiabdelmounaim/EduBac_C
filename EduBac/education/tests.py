import tempfile
from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import StudentProfile, User
from education.curriculum import CURRICULUM
from education.models import Course, Lesson


class LoadCurriculumCommandTests(TestCase):
    def test_loader_is_idempotent_and_preserves_existing_lesson_content(self):
        expected_lessons = sum(len(level['lessons']) for level in CURRICULUM)

        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                call_command('load_curriculum', stdout=StringIO())
                self.assertEqual(Course.objects.count(), len(CURRICULUM))
                self.assertEqual(Lesson.objects.count(), expected_lessons)

                lesson = Lesson.objects.order_by('pk').first()
                lesson.title = 'Titre personnalisé'
                lesson.content = 'Contenu personnalisé'
                lesson.save(update_fields=['title', 'content'])

                call_command('load_curriculum', stdout=StringIO())

        lesson.refresh_from_db()
        self.assertEqual(Course.objects.count(), len(CURRICULUM))
        self.assertEqual(Lesson.objects.count(), expected_lessons)
        self.assertEqual(lesson.title, 'Titre personnalisé')
        self.assertEqual(lesson.content, 'Contenu personnalisé')


class CurriculumAutoLoadViewTests(TestCase):
    def test_level_cards_and_details_use_the_seeded_database_catalog(self):
        self.assertEqual(Course.objects.count(), 0)
        self.assertEqual(Lesson.objects.count(), 0)
        expected_total = sum(len(level['lessons']) for level in CURRICULUM)

        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                response = self.client.get(reverse('education:niveaux'))

                self.assertEqual(response.status_code, 200)
                self.assertEqual(Course.objects.count(), len(CURRICULUM))
                self.assertEqual(Lesson.objects.count(), expected_total)

                expected_counts = {
                    'tronc_commun': 15,
                    '1ere_bac_sc': 12,
                    '2eme_bac_pc': 12,
                    '2eme_bac_sm': 12,
                }
                cards_by_code = {
                    level['link_code']: level
                    for level in response.context['levels']
                }
                for code, expected_count in expected_counts.items():
                    self.assertEqual(
                        cards_by_code[code]['lesson_count'],
                        expected_count,
                    )
                    detail = self.client.get(
                        reverse('education:niveau_detail', kwargs={'niveau': code})
                    )
                    self.assertEqual(detail.status_code, 200)
                    self.assertEqual(
                        len(detail.context['lessons']),
                        expected_count,
                    )

    def test_a_direct_level_visit_seeds_a_fresh_database(self):
        self.assertEqual(Course.objects.count(), 0)

        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                response = self.client.get(
                    reverse(
                        'education:niveau_detail',
                        kwargs={'niveau': 'tronc_commun'},
                    )
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['lessons']), 15)
        self.assertEqual(
            Lesson.objects.count(),
            sum(len(level['lessons']) for level in CURRICULUM),
        )
        sciences_math = self.client.get(
            reverse(
                'education:niveau_detail',
                kwargs={'niveau': '2eme_bac_sm'},
            )
        )
        self.assertEqual(sciences_math.status_code, 200)
        self.assertEqual(len(sciences_math.context['lessons']), 12)

    def login(self, role, niveau=None):
        user = User(username=f'curriculum_{role}', email=f'curriculum-{role}@example.test', role=role)
        user.set_password('test-password')
        user.save()
        if niveau:
            StudentProfile.objects.create(user=user, niveau=niveau)
        session = self.client.session
        session['user_id'] = user.pk
        session.save()
        return user

    def lessons_seen(self):
        """Pour chaque niveau : code HTTP et nombre de leçons affichées."""
        from .curriculum import STUDENT_LEVELS
        vus = {}
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            for item in STUDENT_LEVELS:
                r = self.client.get(reverse('education:niveau_detail', kwargs={'niveau': item['code']}))
                vus[item['code']] = (r.status_code, len(r.context['lessons']) if r.status_code == 200 else None)
            cartes = self.client.get(reverse('education:niveaux')).content.decode()
        return vus, cartes

    def test_every_level_is_visible_to_visitors_students_and_teachers(self):
        """Le niveau du profil ne filtre jamais les niveaux ni leurs leçons."""
        visiteur, cartes_visiteur = self.lessons_seen()
        self.assertTrue(all(code == 200 for code, _ in visiteur.values()), visiteur)
        self.assertEqual(visiteur['2eme_bac_sm'][1], 12)
        eleve_user = self.login('student', niveau='2eme_bac_sm')
        self.assertEqual(self.client.get(reverse('education:niveaux')).wsgi_request.edubac_user, eleve_user)
        eleve, cartes_eleve = self.lessons_seen()
        self.assertEqual(eleve, visiteur)
        prof = self.login('teacher')
        self.assertEqual(self.client.get(reverse('education:niveaux')).wsgi_request.edubac_user, prof)
        enseignant, cartes_enseignant = self.lessons_seen()
        self.assertEqual(enseignant, visiteur)
        from .curriculum import STUDENT_LEVELS
        for item in STUDENT_LEVELS:
            lien = reverse('education:niveau_detail', kwargs={'niveau': item.get('maps_to') or item['code']})
            for page in (cartes_visiteur, cartes_eleve, cartes_enseignant):
                self.assertIn(item['label'], page)
                self.assertIn(lien, page)

    def test_student_opens_lessons_of_another_level(self):
        self.login('student', niveau='2eme_bac_sm')
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            page = self.client.get(reverse('education:niveau_detail', kwargs={'niveau': 'tronc_commun'}))
            self.assertEqual(page.status_code, 200)
            lesson = Lesson.objects.filter(course__niveau='tronc_commun').order_by('order').first()
            # Tous les niveaux restent consultables (titres), mais une leçon ne s'ouvre à l'élève
            # qu'une fois traitée dans l'une de ses classes.
            self.assertContains(page, lesson.title)
            self.assertContains(page, 'data-verrou')
            url = reverse('education:lesson_detail', args=[lesson.pk])
            self.assertEqual(self.client.get(url).status_code, 403)
            from cahier.models import AccesLecon
            from classrooms.models import Classroom, ClassroomMember
            eleve = User.objects.get(username='curriculum_student')
            classe = Classroom.objects.create(name='TC A', niveau='tronc_commun')
            ClassroomMember.objects.create(classroom=classe, user=eleve)
            AccesLecon.objects.create(classroom=classe, lesson=lesson, decision=AccesLecon.OUVERT)
            self.assertEqual(self.client.get(url).status_code, 200)
        self.assertNotContains(page, "n'est pas associé à votre compte")
