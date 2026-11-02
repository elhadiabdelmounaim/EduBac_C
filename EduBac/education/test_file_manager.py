from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .media_library import ai_source_text, chapter_relative
from .models import Course, Lesson, Resources


@override_settings(ALLOWED_HOSTS=['testserver'])
class AdminFileManagerTests(TestCase):
    def setUp(self):
        self.temp_media = TemporaryDirectory()
        self.addCleanup(self.temp_media.cleanup)
        self.media_override = override_settings(MEDIA_ROOT=self.temp_media.name)
        self.media_override.enable()
        self.addCleanup(self.media_override.disable)

        self.course = Course.objects.create(
            name='Mathématiques',
            niveau='1ere_bac_sc',
        )
        self.lesson = Lesson.objects.create(
            course=self.course,
            title='Généralités sur les fonctions numériques',
            order=2,
            content='Contenu de cours existant',
        )
        self.admin_user = get_user_model().objects.create_superuser(
            username='gestionnaire',
            email='gestionnaire@example.test',
            password='not-used-by-force-login',
        )
        self.client.force_login(self.admin_user)
        self.url = reverse('admin:education_course_file_manager')

    def upload(self, category, title, filename, content, **extra):
        return self.client.post(
            self.url,
            {
                'action': 'upload',
                'niveau': self.course.niveau,
                'lecon': str(self.lesson.pk),
                'categorie': category,
                'titre': title,
                'fichier': SimpleUploadedFile(filename, content),
                'confirmer_remplacement': 'yes',
                **extra,
            },
            follow=True,
        )

    def test_admin_dashboard_links_to_the_manager_and_regular_user_is_denied(self):
        response = self.client.get(reverse('admin:index'))
        self.assertContains(response, 'Gestionnaire intelligent des fichiers')
        self.assertContains(response, self.url)

        limited_staff = get_user_model().objects.create_user(
            username='limited_staff',
            email='limited@example.test',
            password='not-used-by-force-login',
            is_staff=True,
        )
        self.client.force_login(limited_staff)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertNotContains(
            self.client.get(reverse('admin:index')),
            'Gestionnaire intelligent des fichiers',
        )

        self.client.force_login(get_user_model().objects.create_user(
            username='student',
            email='student@example.test',
            password='not-used-by-force-login',
        ))
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

    def test_course_pdf_is_saved_in_the_existing_chapter_and_shown_on_site(self):
        response = self.upload(
            'course_pdf',
            'Cours complet',
            'upload.pdf',
            b'%PDF-1.4\nCours EduBac',
        )
        path = (
            Path(self.temp_media.name)
            / chapter_relative(self.lesson)
            / 'Cours'
            / 'cours-complet.pdf'
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(path.is_file())
        self.assertEqual(path.read_bytes(), b'%PDF-1.4\nCours EduBac')
        self.assertContains(
            self.client.get(reverse('education:lesson_detail', args=[self.lesson.pk])),
            'cours-complet.pdf',
        )

    def test_exercise_correction_is_sorted_into_the_existing_exercises_folder(self):
        response = self.upload(
            'correction_pdf',
            'Correction du devoir',
            'correction.pdf',
            b'%PDF-1.4\nCorrection',
        )
        path = (
            Path(self.temp_media.name)
            / chapter_relative(self.lesson)
            / 'Exercices'
            / 'correction-correction-du-devoir.pdf'
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(path.is_file())
        self.assertContains(
            self.client.get(reverse('education:lesson_detail', args=[self.lesson.pk])),
            path.name,
        )

    def test_utf8_ai_source_is_saved_for_the_lesson_without_public_listing(self):
        response = self.upload(
            'ai_source',
            'Règles de calcul',
            'source.txt',
            'قاعدة رياضية\nUne formule : $x^2+1$.'.encode(),
        )
        path = (
            Path(self.temp_media.name)
            / chapter_relative(self.lesson)
            / 'Sources_IA'
            / 'regles-de-calcul.txt'
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(path.is_file())
        self.assertIn('قاعدة رياضية', ai_source_text(self.lesson, 'regles-de-calcul.txt'))
        page = self.client.get(reverse('education:lesson_detail', args=[self.lesson.pk]))
        self.assertNotContains(page, 'regles-de-calcul.txt')

    def test_image_resource_is_linked_and_downloaded_through_django(self):
        image = Image.new('RGB', (2, 2), color='navy')
        buffer = BytesIO()
        image.save(buffer, format='PNG')
        response = self.upload(
            'image',
            'Illustration du chapitre',
            'illustration.png',
            buffer.getvalue(),
        )
        resource = Resources.objects.get(lesson=self.lesson)
        stored = Path(self.temp_media.name) / resource.file.name
        self.assertEqual(response.status_code, 200)
        self.assertTrue(stored.is_file())
        self.assertEqual(resource.name, 'Illustration du chapitre')
        page = self.client.get(reverse('education:lesson_detail', args=[self.lesson.pk]))
        self.assertContains(page, 'Illustration du chapitre')
        download = self.client.get(
            reverse(
                'education:resource_download',
                args=[self.lesson.pk, resource.pk],
            )
        )
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download['Content-Type'], 'image/png')
        self.assertEqual(download['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(b''.join(download.streaming_content), buffer.getvalue())

    def test_duplicate_content_is_not_written_under_a_second_name(self):
        content = '%PDF-1.4\nMême document'.encode()
        self.upload('course_pdf', 'Premier nom', 'one.pdf', content)
        response = self.upload('course_pdf', 'Autre nom', 'two.pdf', content)
        folder = Path(self.temp_media.name) / chapter_relative(self.lesson) / 'Cours'
        self.assertEqual(
            sorted(path.name for path in folder.glob('*.pdf')),
            ['premier-nom.pdf'],
        )
        self.assertContains(response, 'Aucun doublon n’a été créé')

    def test_replacement_options_endpoint_is_limited_to_the_selected_lesson(self):
        self.upload(
            'course_pdf',
            'Cours de logique',
            'logique.pdf',
            b'%PDF-1.4\nCours',
        )
        endpoint = reverse('admin:education_course_file_manager_replacements')
        response = self.client.get(endpoint, {
            'lecon': self.lesson.pk,
            'categorie': 'course_pdf',
        })
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload['options']), 1)
        self.assertEqual(payload['options'][0]['value'], 'file:cours-de-logique.pdf')
        self.assertEqual(
            payload['options'][0]['path'],
            f'{chapter_relative(self.lesson).as_posix()}/Cours/cours-de-logique.pdf',
        )

    def test_replacement_requires_explicit_confirmation_and_preserves_old_file(self):
        original = b'%PDF-1.4\nAncienne version'
        replacement = b'%PDF-1.4\nNouvelle version'
        self.upload('course_pdf', 'Cours à garder', 'one.pdf', original)
        response = self.client.post(
            self.url,
            {
                'action': 'upload',
                'niveau': self.course.niveau,
                'lecon': str(self.lesson.pk),
                'categorie': 'course_pdf',
                'titre': 'Cours à garder',
                'fichier': SimpleUploadedFile('two.pdf', replacement),
            },
        )
        path = (
            Path(self.temp_media.name)
            / chapter_relative(self.lesson)
            / 'Cours'
            / 'cours-a-garder.pdf'
        )
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'confirmation')

        response = self.upload(
            'course_pdf',
            'Cours à garder',
            'two.pdf',
            replacement,
            remplacer_fichier='file:cours-a-garder.pdf',
        )
        self.assertEqual(path.read_bytes(), replacement)
        self.assertContains(response, 'Fichier remplacé')

    def test_invalid_format_and_cross_level_lesson_are_rejected(self):
        response = self.upload(
            'course_pdf',
            'Document incorrect',
            'document.txt',
            b'not a PDF',
        )
        self.assertContains(response, 'Format non autorisé')
        self.assertFalse(
            (Path(self.temp_media.name) / chapter_relative(self.lesson) / 'Cours')
            .joinpath('document-incorrect.txt').exists()
        )

        other_course = Course.objects.create(
            name='Autre niveau',
            niveau='2eme_bac_pc',
        )
        other_lesson = Lesson.objects.create(
            course=other_course,
            title='Leçon distante',
            order=1,
            content='',
        )
        response = self.client.post(
            self.url,
            {
                'action': 'upload',
                'niveau': self.course.niveau,
                'lecon': str(other_lesson.pk),
                'categorie': 'course_pdf',
                'titre': 'Cours',
                'fichier': SimpleUploadedFile('cours.pdf', b'%PDF-1.4\nTest'),
                'confirmer_remplacement': 'yes',
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'ne correspond pas au niveau')

    def test_course_markdown_does_not_create_a_second_markdown_file(self):
        folder = Path(self.temp_media.name) / chapter_relative(self.lesson) / 'Cours'
        folder.mkdir(parents=True)
        (folder / 'cours-existant.md').write_text('# Déjà présent', encoding='utf-8')
        response = self.upload(
            'course_markdown',
            'Nouveau cours',
            'nouveau.md',
            b'# Nouveau cours',
        )
        self.assertEqual(
            [path.name for path in folder.glob('*.md')],
            ['cours-existant.md'],
        )
        self.assertContains(response, 'un autre fichier Markdown')

    def test_existing_legacy_markdown_can_be_replaced_without_changing_its_path(self):
        folder = Path(self.temp_media.name) / chapter_relative(self.lesson) / 'Cours'
        folder.mkdir(parents=True)
        original_path = folder / 'cours_fonctions.md'
        original_path.write_text('# Ancienne version', encoding='utf-8')
        manager_url = (
            f'{self.url}?niveau={self.course.niveau}'
            f'&lecon={self.lesson.pk}&categorie=course_markdown'
        )
        response = self.client.get(manager_url)
        self.assertContains(response, 'file:cours_fonctions.md')

        response = self.client.post(
            self.url,
            {
                'action': 'upload',
                'niveau': self.course.niveau,
                'lecon': str(self.lesson.pk),
                'categorie': 'course_markdown',
                'titre': 'Nouveau titre du cours',
                'remplacer_fichier': 'file:cours_fonctions.md',
                'fichier': SimpleUploadedFile('remplacement.md', b'# Nouvelle version'),
                'confirmer_remplacement': 'yes',
            },
            follow=True,
        )
        self.assertEqual(original_path.read_text(encoding='utf-8'), '# Nouvelle version')
        self.assertFalse((folder / 'nouveau-titre-du-cours.md').exists())
        self.assertContains(response, 'Fichier remplacé')

    def test_delete_requires_confirmation_and_is_scoped_to_the_selected_lesson(self):
        self.upload(
            'exercise_pdf',
            'Série de révision',
            'serie.pdf',
            b'%PDF-1.4\nExercises',
        )
        path = (
            Path(self.temp_media.name)
            / chapter_relative(self.lesson)
            / 'Exercices'
            / 'exercices-serie-de-revision.pdf'
        )
        response = self.client.post(
            self.url,
            {
                'action': 'delete',
                'lecon': str(self.lesson.pk),
                'categorie': 'exercise_pdf',
                'filename': path.name,
            },
            follow=True,
        )
        self.assertTrue(path.is_file())
        self.assertContains(response, 'Cochez la confirmation')

        response = self.client.post(
            self.url,
            {
                'action': 'delete',
                'lecon': str(self.lesson.pk),
                'categorie': 'exercise_pdf',
                'filename': path.name,
                'confirmer_suppression': 'yes',
            },
            follow=True,
        )
        self.assertFalse(path.exists())
        self.assertContains(response, 'Fichier supprimé')

    def test_resource_download_cannot_be_reused_for_another_lesson(self):
        resource = Resources.objects.create(
            name='Document',
            type='pdf',
            lesson=self.lesson,
            file='resources/not-present.pdf',
        )
        another_course = Course.objects.create(
            name='Deuxième cours',
            niveau='2eme_bac_pc',
        )
        other_lesson = Lesson.objects.create(
            course=another_course,
            title='Autre leçon',
            order=1,
            content='',
        )
        response = self.client.get(
            reverse(
                'education:resource_download',
                args=[other_lesson.pk, resource.pk],
            )
        )
        self.assertEqual(response.status_code, 404)

    def test_resource_view_does_not_expose_chat_attachments(self):
        private_file = Path(self.temp_media.name) / 'chat' / 'voice.webm'
        private_file.parent.mkdir(parents=True)
        private_file.write_bytes(b'private voice message')
        resource = Resources.objects.create(
            name='Pièce jointe privée',
            type='doc',
            lesson=self.lesson,
            file='chat/voice.webm',
        )
        response = self.client.get(
            reverse(
                'education:resource_download',
                args=[self.lesson.pk, resource.pk],
            )
        )
        self.assertEqual(response.status_code, 404)
        manager = self.client.get(
            self.url,
            {
                'niveau': self.course.niveau,
                'lecon': self.lesson.pk,
                'categorie': 'document',
            },
        )
        self.assertNotContains(manager, 'voice.webm')
