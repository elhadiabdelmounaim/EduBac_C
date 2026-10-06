import tempfile
from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

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
        self.assertEqual(Lesson.objects.count(), 79)
