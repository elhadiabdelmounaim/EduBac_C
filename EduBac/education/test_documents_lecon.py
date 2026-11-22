"""Page d'une leçon : boutons COURS et EXERCICES (Ouvrir / Télécharger), documents gérés dans l'admin."""
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .media_library import chapter_relative
from .models import Course, Lesson, Resources


@override_settings(ALLOWED_HOSTS=['testserver'])
class DocumentsLeconTests(TestCase):
    def setUp(self):
        media = TemporaryDirectory()
        self.addCleanup(media.cleanup)
        reglage = override_settings(MEDIA_ROOT=media.name)
        reglage.enable()
        self.addCleanup(reglage.disable)
        self.media = Path(media.name)
        course = Course.objects.create(name='Mathématiques', niveau='2eme_bac_pc')
        self.lesson = Lesson.objects.create(course=course, title='Limites et continuité', order=1, content='x')
        self.url = reverse('education:lesson_detail', args=[self.lesson.pk])

    def ressource(self, nom, fichier, contenu, categorie, **extra):
        return Resources.objects.create(lesson=self.lesson, name=nom, categorie=categorie,
                                        file=SimpleUploadedFile(fichier, contenu), **extra)

    def test_two_buttons_list_course_and_exercise_documents(self):
        dossier = self.media / chapter_relative(self.lesson)
        (dossier / 'Cours').mkdir(parents=True)
        (dossier / 'Exercices').mkdir(parents=True)
        (dossier / 'Cours' / 'limites.pdf').write_bytes(b'%PDF-1.4\ncours')
        (dossier / 'Exercices' / 'serie-1.pdf').write_bytes(b'%PDF-1.4\nserie')
        resume = self.ressource('Résumé', 'resume.pdf', b'%PDF-1.4\nresume', 'cours', ordre=1)
        serie = self.ressource('Série 2 (Word)', 'serie2.docx', b'PK\x03\x04', 'exercices',
                               description='À rendre lundi.', type='doc')
        annexe = self.ressource('Fiche GeoGebra', 'annexe.ggb', b'PK', 'autre', type='doc')
        page = self.client.get(self.url).content.decode()
        self.assertIn('aria-controls="docs-cours"', page)
        self.assertIn('aria-controls="docs-exercices"', page)
        self.assertIn('<span class="lesson-docs__libelle">COURS</span>', page)
        self.assertIn('<span class="lesson-docs__libelle">EXERCICES</span>', page)
        cours = page[page.index('id="docs-cours"'):page.index('id="docs-exercices"')]
        exercices = page[page.index('id="docs-exercices"'):]
        dossier_pdf = reverse('education:lesson_document', args=[self.lesson.pk, 'Cours', 'limites.pdf'])
        self.assertIn(f'href="{dossier_pdf}">Ouvrir</a>', cours)
        self.assertIn(f'href="{dossier_pdf}?download=1" download>Télécharger</a>', cours)
        url_resume = reverse('education:resource_download', args=[self.lesson.pk, resume.pk])
        self.assertIn(f'href="{url_resume}">Ouvrir</a>', cours)
        self.assertIn('serie-1.pdf', exercices)
        self.assertIn('Série 2 (Word)', exercices)
        self.assertIn('À rendre lundi.', exercices)
        url_serie = reverse('education:resource_download', args=[self.lesson.pk, serie.pk])
        self.assertNotIn(f'href="{url_serie}">Ouvrir</a>', exercices)      # Word : pas lisible dans le navigateur
        self.assertIn(f'href="{url_serie}?download=1" download>Télécharger</a>', exercices)
        self.assertNotIn('Série 2 (Word)', cours)
        self.assertIn('2 documents', page)
        # Les autres ressources restent dans « Ressources pédagogiques complémentaires ».
        self.assertIn('Ressources pédagogiques complémentaires', page)
        self.assertNotIn('Fiche GeoGebra', cours + page[page.index('id="docs-exercices"'):page.index('Ressources pédagogiques')])
        self.assertIn(reverse('education:resource_download', args=[self.lesson.pk, annexe.pk]), page)

    def test_empty_lesson_still_offers_both_buttons(self):
        page = self.client.get(self.url).content.decode()
        self.assertEqual(page.count('Aucun document pour le moment.'), 2)
        self.assertIn('0 document', page)

    def test_pdf_opens_in_the_browser_and_other_formats_download(self):
        pdf = self.ressource('Cours', 'cours.pdf', b'%PDF-1.4\nx', 'cours')
        doc = self.ressource('Cours Word', 'cours.docx', b'PK\x03\x04', 'cours', type='pdf')
        r = self.client.get(reverse('education:resource_download', args=[self.lesson.pk, pdf.pk]))
        self.assertTrue(r['Content-Disposition'].startswith('inline'))
        self.assertEqual(r['Content-Type'], 'application/pdf')
        r = self.client.get(reverse('education:resource_download', args=[self.lesson.pk, pdf.pk]), {'download': '1'})
        self.assertTrue(r['Content-Disposition'].startswith('attachment'))
        r = self.client.get(reverse('education:resource_download', args=[self.lesson.pk, doc.pk]))
        self.assertTrue(r['Content-Disposition'].startswith('attachment'))

    def test_unexpected_extensions_are_refused_by_the_admin_form(self):
        from django.core.exceptions import ValidationError
        mauvais = Resources(lesson=self.lesson, name='Script', categorie='cours',
                            file=SimpleUploadedFile('virus.exe', b'MZ'))
        with self.assertRaises(ValidationError):
            mauvais.full_clean()


@override_settings(ALLOWED_HOSTS=['testserver'])
class AdminDocumentsTests(TestCase):
    def setUp(self):
        media = TemporaryDirectory()
        self.addCleanup(media.cleanup)
        reglage = override_settings(MEDIA_ROOT=media.name)
        reglage.enable()
        self.addCleanup(reglage.disable)
        self.media = Path(media.name)
        course = Course.objects.create(name='Mathématiques', niveau='1ere_bac_sm')
        self.lesson = Lesson.objects.create(course=course, title='Arithmétique', order=3, content='x')
        admin = get_user_model().objects.create_superuser(username='admin', email='a@example.test', password='x')
        self.client.force_login(admin)

    def formulaire(self, **extra):
        data = {
            'course': self.lesson.course.pk, 'title': self.lesson.title, 'order': '3',
            'duree_prevue_minutes': '480', 'content': 'x', 'summary': '', 'faq': '',
            'resources-TOTAL_FORMS': '2', 'resources-INITIAL_FORMS': '0',
            'resources-MIN_NUM_FORMS': '0', 'resources-MAX_NUM_FORMS': '1000',
        }
        data.update(extra)
        return data

    def test_several_documents_per_lesson_and_planned_duration(self):
        url = reverse('admin:education_lesson_change', args=[self.lesson.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        r = self.client.post(url, self.formulaire(**{
            'resources-0-categorie': 'cours', 'resources-0-ordre': '0', 'resources-0-name': 'Cours complet',
            'resources-0-description': 'Version 2026', 'resources-0-type': 'pdf',
            'resources-0-file': SimpleUploadedFile('cours.pdf', b'%PDF-1.4\nc'),
            'resources-1-categorie': 'exercices', 'resources-1-ordre': '0', 'resources-1-name': 'Série 1',
            'resources-1-description': '', 'resources-1-type': 'doc',
            'resources-1-file': SimpleUploadedFile('serie.docx', b'PK\x03\x04'),
        }))
        self.assertEqual(r.status_code, 302, r.content.decode()[:2000])
        self.lesson.refresh_from_db()
        self.assertEqual(self.lesson.duree_prevue_minutes, 480)
        self.assertEqual(sorted(self.lesson.resources.values_list('categorie', flat=True)), ['cours', 'exercices'])
        liste = self.client.get(reverse('admin:education_lesson_changelist')).content.decode()
        self.assertIn('8 h', liste)

    def test_replacing_a_file_removes_the_old_one(self):
        res = Resources.objects.create(lesson=self.lesson, name='Cours', categorie='cours',
                                       file=SimpleUploadedFile('v1.pdf', b'%PDF-1.4\nv1'))
        ancien = self.media / res.file.name
        self.assertTrue(ancien.is_file())
        res.file = SimpleUploadedFile('v2.pdf', b'%PDF-1.4\nv2')
        res.save()
        self.assertFalse(ancien.exists())
        self.assertTrue((self.media / res.file.name).is_file())
        res.delete()
        self.assertFalse(any((self.media / 'resources').iterdir()))
