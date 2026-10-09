from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

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

    def test_live_pdf_listing_download_and_utf8_ai_sources(self):
        course = Course.objects.create(name='Maths', niveau='1ere_bac_sm')
        lesson = Lesson.objects.create(course=course, title='Logique', order=1, content='Contenu DB')
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            call_command('organize_media')
            chapter = Path(media) / 'lessons/1sm/01_logique'
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
