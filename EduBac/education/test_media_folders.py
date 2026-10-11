from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from education.models import Course, Lesson


class MediaFoldersTests(TestCase):
    def test_course_markdown_is_displayed_and_reread_without_database_import(self):
        from education.media_library import chapter_relative
        course = Course.objects.create(name='Mathématiques', niveau='1ere_bac_sc')
        lesson = Lesson.objects.create(
            course=course, title='Généralités sur les fonctions numériques',
            order=2, content='Ancien contenu',
        )
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            folder = Path(media) / chapter_relative(lesson) / 'Cours'
            folder.mkdir(parents=True)
            source = folder / 'fonctions.md'
            text = '# Fonctions\n\nUne formule : \\(f(x)=\\frac{1}{x}\\).\n'
            source.write_text(text, encoding='utf-8')
            url = reverse('education:lesson_detail', args=[lesson.pk])
            response = self.client.get(url)
            self.assertContains(response, '<h1>Fonctions</h1>', html=True)
            self.assertContains(response, r'$f(x)=\frac{1}{x}$')
            self.assertNotContains(response, 'Ancien contenu')
            self.assertEqual(lesson.get_content(), text)
            source.write_text('# Cours mis à jour', encoding='utf-8')
            self.assertContains(self.client.get(url), 'Cours mis à jour')
            lesson.refresh_from_db()
            self.assertEqual(lesson.content, 'Ancien contenu')
            self.assertEqual(Lesson.objects.count(), 1)
            self.assertEqual(list(folder.iterdir()), [source])
            source.unlink()
            self.assertContains(self.client.get(url), 'Ancien contenu')

    def test_course_markdown_rejects_duplicates_empty_and_invalid_encoding(self):
        from education.media_library import chapter_relative
        course = Course.objects.create(name='Mathématiques', niveau='1ere_bac_sc')
        lesson = Lesson.objects.create(course=course, title='Fonctions', order=2, content='DB')
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            folder = Path(media) / chapter_relative(lesson) / 'Cours'
            folder.mkdir(parents=True)
            source = folder / 'cours.md'
            source.write_text('# Cours', encoding='utf-8')
            duplicate = folder / 'copie.MD'
            duplicate.write_text('# Copie', encoding='utf-8')
            url = reverse('education:lesson_detail', args=[lesson.pk])
            self.assertContains(self.client.get(url), 'Plusieurs fichiers Markdown')
            duplicate.unlink()
            source.write_text('', encoding='utf-8')
            self.assertContains(self.client.get(url), 'est vide')
            source.write_bytes(b'\xff')
            self.assertContains(self.client.get(url), 'encodage UTF-8')

    def test_course_markdown_does_not_read_other_levels_or_ai_sources(self):
        from education.media_library import chapter_relative
        course = Course.objects.create(name='Mathématiques', niveau='1ere_bac_sc')
        lesson = Lesson.objects.create(course=course, title='Fonctions', order=2, content='DB')
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            chapter = Path(media) / chapter_relative(lesson)
            (chapter / 'Sources_IA').mkdir(parents=True)
            (chapter / 'Sources_IA' / 'cours.md').write_text('Source IA', encoding='utf-8')
            other = Path(media) / 'lessons/1BAC_SM/02_fonctions/Cours'
            other.mkdir(parents=True)
            (other / 'cours.md').write_text('Autre niveau', encoding='utf-8')
            self.assertEqual(lesson.get_content(), 'DB')

    @patch('education.views._ensure_curriculum_loaded')
    def test_level_page_discovers_course_and_exercise_pdfs_without_database_import(self, load):
        from education.media_library import chapter_relative
        course = Course.objects.create(name='Mathématiques', niveau='1ere_bac_lettres')
        lesson = Lesson.objects.create(course=course, title='Notions de logique', order=1)
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            chapter = Path(media) / chapter_relative(lesson)
            for kind in ('Cours', 'Exercices', 'Sources_IA'):
                (chapter / kind).mkdir(parents=True)
            pdf = chapter / 'Cours' / 'logique.PDF'
            exercise = chapter / 'Exercices' / 'Série été.pdf'
            source = chapter / 'Sources_IA' / 'Source réservée.txt'
            pdf.write_bytes(b'%PDF-1.4\nTest')
            exercise.write_bytes(b'%PDF-1.4\nExercices')
            source.write_text('Source pédagogique', encoding='utf-8')
            level_url = reverse('education:niveau_detail', args=[course.niveau])
            response = self.client.get(level_url)
            self.assertContains(response, pdf.name)
            self.assertContains(response, exercise.name)
            self.assertNotContains(response, source.name)
            self.assertContains(response, reverse('education:lesson_document',
                                                 args=[lesson.pk, 'Cours', pdf.name]))
            self.assertContains(response, reverse('education:lesson_detail', args=[lesson.pk]))
            pdf.unlink()
            response = self.client.get(level_url)
            self.assertNotContains(response, pdf.name)
            self.assertContains(response, exercise.name)
            exercise.unlink()
            self.assertContains(self.client.get(level_url), 'Fichier bientôt disponible')

    @patch('education.views._ensure_curriculum_loaded')
    def test_level_page_preserves_legacy_pdf_links(self, load):
        course = Course.objects.create(name='Mathématiques', niveau='1ere_bac_lettres')
        Lesson.objects.create(course=course, title='Logique', order=1, pdf='ancien.pdf')
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            (Path(media) / 'ancien.pdf').write_bytes(b'%PDF-1.4\nTest')
            self.assertContains(
                self.client.get(reverse('education:niveau_detail', args=[course.niveau])),
                '/media/ancien.pdf',
            )

    def test_all_lessons_have_folders_without_overwriting_files(self):
        course = Course.objects.create(name='Mathématiques', niveau='1ere_bac_sm')
        lesson = Lesson.objects.create(course=course, title='Logique', order=1, content='Original')
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            legacy = Path(media) / 'lessons' / '1BAC_SM' / '01.md'
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

    def test_live_pdf_listing_download_and_utf8_ai_sources(self):
        course = Course.objects.create(name='Maths', niveau='1ere_bac_sm')
        lesson = Lesson.objects.create(course=course, title='Logique', order=1, content='Contenu DB')
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            call_command('organize_media')
            chapter = Path(media) / 'lessons/1BAC_SM/01_logique'
            source = chapter / 'Sources_IA' / 'Règles.txt'
            source.write_text('قاعدة\nLa formule est $x^2+1$.', encoding='utf-8')
            self.assertIn('قاعدة', lesson.get_ai_help()['contenu'])
            self.assertIn('$x^2+1$', lesson.get_ai_help()['contenu'])
            pdf = chapter / 'Cours' / 'Mon cours été.PDF'
            pdf.write_bytes(b'%PDF-1.4\nTest')
            page_url = reverse('education:lesson_detail', args=[lesson.pk])
            self.assertContains(self.client.get(page_url), pdf.name)
            self.assertNotContains(self.client.get(page_url), 'Règles.txt')
            url = reverse('education:lesson_document', args=[lesson.pk, 'Cours', pdf.name])
            response = self.client.get(url + '?download=1')
            self.assertEqual(response.status_code, 200)
            self.assertIn('attachment', response['Content-Disposition'])
            self.assertEqual(b''.join(response.streaming_content), pdf.read_bytes())
            self.assertEqual(self.client.get(reverse(
                'education:lesson_document', args=[lesson.pk, 'Sources_IA', source.name]
            )).status_code, 404)
            source.write_text('Nouvelle règle', encoding='utf-8')
            self.assertIn('Nouvelle règle', lesson.get_ai_help()['contenu'])
            pdf.unlink()
            self.assertNotContains(self.client.get(page_url), pdf.name)
            self.assertEqual(self.client.get(url).status_code, 404)
