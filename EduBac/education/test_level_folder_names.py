from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse

from .media_library import LEVEL_FOLDERS, ai_source_text, chapter_relative, documents
from .models import Course, Lesson


class LevelFolderNamesTests(TestCase):
    def setUp(self):
        self.course = Course.objects.create(name='Mathématiques', niveau='1ere_bac_lettres')
        self.lesson = Lesson.objects.create(course=self.course, title='Notions de logique', order=1)

    def run_command(self, *args, **kwargs):
        call_command(*args, stdout=StringIO(), **kwargs)

    def test_exact_abbreviations_and_reserved_empty_folders(self):
        self.assertEqual(set(LEVEL_FOLDERS.values()), {
            'TCL', 'TCS', 'TCT', '1BAC_SE', '1BAC_L', '1BAC_SM',
            '2BAC_SVT', '2BAC_PC', '2BAC_L', '2BAC_SM',
        })
        self.assertEqual(str(chapter_relative(self.lesson)),
                         'lessons/1BAC_L/01_notions-de-logique')
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            self.run_command('organize_media')
            for level in ('TCL', 'TCT'):
                self.assertEqual([p.name for p in (Path(media) / 'lessons' / level).iterdir()],
                                 ['.gitkeep'])
            self.assertEqual(Lesson.objects.count(), 1)

    @patch('education.views._ensure_curriculum_loaded')
    def test_rename_preserves_files_ids_links_and_ai_source(self, load):
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            old = Path(media) / 'lessons/1let/01_notions-de-logique'
            for kind in ('Cours', 'Exercices', 'Sources_IA'):
                (old / kind).mkdir(parents=True)
            original = b'%PDF-1.4\nOriginal'
            (old / 'Cours/logique.pdf').write_bytes(original)
            source_text = 'منطق : $x^2+1$'
            (old / 'Sources_IA/logique.txt').write_text(source_text, encoding='utf-8')
            self.lesson.pdf.name = 'lessons/1let/01_notions-de-logique/Cours/logique.pdf'
            self.lesson.save(update_fields=['pdf'])
            before = (self.lesson.pk, self.course.pk, self.lesson.title, self.course.niveau)
            self.run_command('normalize_level_folders')
            self.lesson.refresh_from_db()
            target = Path(media) / chapter_relative(self.lesson)
            self.assertFalse(old.exists())
            self.assertEqual((target / 'Cours/logique.pdf').read_bytes(), original)
            self.assertEqual((target / 'Sources_IA/logique.txt').read_text(encoding='utf-8'),
                             source_text)
            self.assertEqual(
                (self.lesson.pk, self.course.pk, self.lesson.title, self.course.niveau), before)
            self.assertEqual(self.lesson.pdf.name,
                             'lessons/1BAC_L/01_notions-de-logique/Cours/logique.pdf')
            self.assertIn(source_text, ai_source_text(self.lesson))
            url = reverse('education:lesson_document',
                          args=[self.lesson.pk, 'Cours', 'logique.pdf'])
            response = self.client.get(url + '?download=1')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(b''.join(response.streaming_content), original)
            self.assertContains(self.client.get(reverse('education:niveau_detail',
                                                       args=[self.course.niveau])), 'logique.pdf')
            self.run_command('normalize_level_folders')
            self.assertEqual(len(list(Path(media).rglob('logique.pdf'))), 1)

    def test_dry_run_never_changes_files_or_database(self):
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            old = Path(media) / 'lessons/1let'
            old.mkdir(parents=True)
            (old / '01.pdf').write_bytes(b'Original')
            self.lesson.pdf.name = 'lessons/1let/01.pdf'
            self.lesson.save(update_fields=['pdf'])
            self.run_command('normalize_level_folders', dry_run=True)
            self.lesson.refresh_from_db()
            self.assertTrue(old.exists())
            self.assertFalse((old.parent / '1BAC_L').exists())
            self.assertEqual(self.lesson.pdf.name, 'lessons/1let/01.pdf')

    def test_conflict_aborts_all_moves_without_overwriting(self):
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            root = Path(media) / 'lessons'
            for level in ('tc', '1let', '1BAC_L'):
                (root / level).mkdir(parents=True)
                (root / level / 'preuve.txt').write_text(level)
            with self.assertRaises(CommandError):
                self.run_command('normalize_level_folders')
            self.assertTrue((root / 'tc').exists())
            self.assertFalse((root / 'TCS').exists())
            self.assertEqual((root / '1let/preuve.txt').read_text(), '1let')
            self.assertEqual((root / '1BAC_L/preuve.txt').read_text(), '1BAC_L')

    def test_failed_move_restores_prior_directory_renames(self):
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            root = Path(media) / 'lessons'
            for level in ('tc', '1let'):
                (root / level).mkdir(parents=True)
            rename = Path.rename

            def fail_second(source, target):
                if source.name == '1let':
                    raise OSError('Erreur simulée')
                return rename(source, target)

            with patch.object(Path, 'rename', autospec=True, side_effect=fail_second):
                with self.assertRaises(OSError):
                    self.run_command('normalize_level_folders')
            self.assertTrue((root / 'tc').exists())
            self.assertTrue((root / '1let').exists())
            self.assertFalse((root / 'TCS').exists())

    def test_legacy_markdown_lookup_uses_canonical_folder(self):
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            level = Path(media) / 'lessons/1BAC_L'
            level.mkdir(parents=True)
            text = 'Support Markdown conservé. ' * 10
            (level / '01.md').write_text(text, encoding='utf-8')
            self.assertIn(text.strip(), self.lesson.get_full_pedagogical_text())
            self.assertEqual(documents(self.lesson, 'Cours'), [])

    def test_curriculum_links_existing_pdf_without_copying_it(self):
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            level = Path(media) / 'lessons/1BAC_L'
            level.mkdir(parents=True)
            (level / '01.pdf').write_bytes(b'%PDF-1.4\nOriginal')
            self.run_command('load_curriculum')
            self.lesson.refresh_from_db()
            self.assertEqual(self.lesson.pdf.name, 'lessons/1BAC_L/01.pdf')
            self.assertEqual(len(list(Path(media).rglob('*.pdf'))), 1)
