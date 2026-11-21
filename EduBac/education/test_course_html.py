import tempfile
from pathlib import Path

from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Course, Lesson


@override_settings(ALLOWED_HOSTS=['testserver'])
class CourseHtmlTests(TestCase):
    """Cours en ligne (HTML) : « Ouvrir » affiche le cours, « Télécharger » garde le PDF."""

    def setUp(self):
        self.temp_media = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_media.cleanup)
        override = override_settings(MEDIA_ROOT=self.temp_media.name)
        override.enable()
        self.addCleanup(override.disable)
        self.course = Course.objects.create(name='Mathématiques', niveau='1ere_bac_sc')
        self.lesson = Lesson.objects.create(
            title='Le produit scalaire dans le plan', content='', course=self.course, order=4)
        self.other = Lesson.objects.create(
            title='Les suites numériques', content='', course=self.course, order=5)

    def add_pdf(self, lesson_folder, name='produit_scalaire.pdf'):
        folder = Path(self.temp_media.name) / 'lessons' / '1BAC_SE' / lesson_folder / 'Cours'
        folder.mkdir(parents=True)
        (folder / name).write_bytes(b'%PDF-1.4\nEduBac\n')
        return name

    def test_course_page_uses_local_static_files(self):
        response = self.client.get(reverse('education:lesson_course_html', args=[self.lesson.pk]))
        self.assertEqual(response.status_code, 200)
        page = response.content.decode()
        self.assertIn('/static/vendor/jquery/jquery-3.7.1.min.js', page)
        self.assertIn('/static/js/cours.js', page)
        self.assertIn('/static/vendor/mathjax/tex-svg-3.2.2.js', page)
        self.assertIn('/static/css/cours.css', page)
        self.assertNotIn('cdnjs', page)
        # Le LaTeX est transmis tel quel (pas interprété par Django).
        self.assertIn(r"\[\vu\cdot\vv=xx'+yy'", page)
        self.assertEqual(page.count('class="chap"'), 9)
        self.assertContains(response, reverse('education:lesson_detail', args=[self.lesson.pk]))

    def test_lesson_without_html_course_returns_404(self):
        response = self.client.get(reverse('education:lesson_course_html', args=[self.other.pk]))
        self.assertEqual(response.status_code, 404)

    def test_open_button_shows_html_and_download_keeps_pdf(self):
        name = self.add_pdf('04_le-produit-scalaire-dans-le-plan')
        html_url = reverse('education:lesson_course_html', args=[self.lesson.pk])
        pdf_url = reverse('education:lesson_document', args=[self.lesson.pk, 'Cours', name])
        page = self.client.get(reverse('education:lesson_detail', args=[self.lesson.pk])).content.decode()
        self.assertIn(f'href="{html_url}">Ouvrir</a>', page)
        self.assertIn(f'href="{pdf_url}?download=1"', page)
        self.assertNotIn(f'href="{pdf_url}">Ouvrir</a>', page)

    def test_lesson_without_html_course_keeps_pdf_open_button(self):
        name = self.add_pdf('05_les-suites-numeriques', 'suites.pdf')
        pdf_url = reverse('education:lesson_document', args=[self.other.pk, 'Cours', name])
        page = self.client.get(reverse('education:lesson_detail', args=[self.other.pk])).content.decode()
        self.assertIn(f'href="{pdf_url}">Ouvrir</a>', page)
        self.assertNotIn(reverse('education:lesson_course_html', args=[self.other.pk]), page)

    def test_html_course_is_offered_even_without_pdf(self):
        page = self.client.get(reverse('education:lesson_detail', args=[self.lesson.pk])).content.decode()
        self.assertIn('Cours en ligne', page)
        self.assertIn(reverse('education:lesson_course_html', args=[self.lesson.pk]), page)
