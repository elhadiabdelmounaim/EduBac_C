import tempfile
from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings

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
