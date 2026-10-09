from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.test import TestCase, override_settings

from education.models import Course, Lesson


class MediaFoldersTests(TestCase):
    def test_all_lessons_have_folders_without_overwriting_files(self):
        course = Course.objects.create(name='Mathématiques', niveau='1ere_bac_sm')
        lesson = Lesson.objects.create(course=course, title='Logique', order=1, content='Original')
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            legacy = Path(media) / 'lessons' / '1sm' / '01.md'
            legacy.parent.mkdir(parents=True)
            legacy.write_text('Cours existant', encoding='utf-8')
            call_command('organize_media')
            chapter = legacy.parent / '01_logique'
            self.assertTrue((chapter / 'Cours').is_dir())
            self.assertTrue((chapter / 'Exercices').is_dir())
            uploaded = chapter / 'Exercices' / 'serie.txt'
            uploaded.write_text('Exercice existant', encoding='utf-8')
            call_command('organize_media')
            self.assertEqual(legacy.read_text(), 'Cours existant')
            self.assertEqual(uploaded.read_text(), 'Exercice existant')
            lesson.refresh_from_db()
            self.assertEqual(lesson.content, 'Original')
