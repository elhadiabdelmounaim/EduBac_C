import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Course, Lesson


@override_settings(ALLOWED_HOSTS=['testserver'])
class LessonPdfDownloadTests(TestCase):
    def setUp(self):
        self.temp_media = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_media.cleanup)
        self.media_override = override_settings(MEDIA_ROOT=self.temp_media.name)
        self.media_override.enable()
        self.addCleanup(self.media_override.disable)
        course = Course.objects.create(
            name='Mathématiques',
            niveau='tronc_commun',
        )
        self.pdf_data = b'%PDF-1.4\nEduBac test file\n'
        self.lesson = Lesson.objects.create(
            title='Leçon de test',
            content='Contenu de test',
            course=course,
            order=1,
            pdf=SimpleUploadedFile(
                'support.pdf',
                self.pdf_data,
                content_type='application/pdf',
            ),
        )

    def test_pdf_is_served_through_a_django_view(self):
        response = self.client.get(
            reverse('education:lesson_pdf', args=[self.lesson.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertEqual(
            b''.join(response.streaming_content),
            self.pdf_data,
        )
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(response['Cache-Control'], 'private, no-store')

    def test_download_query_sets_attachment_disposition(self):
        response = self.client.get(
            reverse('education:lesson_pdf', args=[self.lesson.pk]),
            {'download': '1'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment', response['Content-Disposition'])
