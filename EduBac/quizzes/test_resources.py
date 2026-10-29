"""Resource extraction, selection boundaries, and teacher-to-AI transport."""
import json
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from pypdf import PdfWriter

from accounts.models import User, TeacherProfile
from ai.services import AIService
from education.media_library import chapter_relative
from education.models import Course, Lesson, Resources
from .models import Quiz
from .resources import extract_document, prepare_resources, resource_catalog


QUIZ_DATA = {
    'title': 'Quiz guidé',
    'questions': [{
        'text': 'Résoudre $3x + 2 = 11$.',
        'choices': [
            {'text': str(number), 'is_correct': number == 3} for number in (1, 2, 3, 4)
        ],
        'explanation': 'Soustraire 2 puis diviser par 3.',
        'hint': 'Isoler le terme contenant x.',
    }],
}


def upload(name='Consignes.txt', text='Équations linéaires : isoler x.'):
    return SimpleUploadedFile(name, text.encode('utf-8'), content_type='text/plain')


def docx_bytes(text):
    handle = BytesIO()
    with ZipFile(handle, 'w') as archive:
        archive.writestr('word/document.xml', (
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f'<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>'
        ))
    return handle.getvalue()


def pdf_bytes():
    """A minimal real PDF with a selectable text stream, not a mocked parser."""
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    font = DictionaryObject({
        NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'),
        NameObject('/BaseFont'): NameObject('/Helvetica'),
    })
    page[NameObject('/Resources')] = DictionaryObject({
        NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)}),
    })
    stream = DecodedStreamObject()
    stream.set_data(b'BT /F1 12 Tf 20 250 Td (PDF_SELECTED_MARKER Equations lineaires) Tj ET')
    page[NameObject('/Contents')] = writer._add_object(stream)
    result = BytesIO()
    writer.write(result)
    return result.getvalue()


@override_settings(ALLOWED_HOSTS=['testserver'], QUIZ_SEMANTIC_CHECK_ENABLED=False)
class TeacherResourceTests(TestCase):
    def setUp(self):
        from ai.test_helpers import isolate_protocol_checks
        isolate_protocol_checks(self)
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        settings = override_settings(MEDIA_ROOT=temporary.name)
        settings.enable()
        self.addCleanup(settings.disable)
        self.media = Path(temporary.name)
        course = Course.objects.create(name='Maths', niveau='tronc_commun')
        self.lesson = Lesson.objects.create(
            course=course, title='Équations', order=1, content='HIDDEN_LESSON_CONTENT',
        )
        self.folder = self.media / chapter_relative(self.lesson) / 'Sources_IA'
        self.folder.mkdir(parents=True)
        (self.folder / 'Règles.txt').write_text('SELECTED_SOURCE_A : $2x=6$.', encoding='utf-8')
        (self.folder / 'Méthodes.txt').write_text('SELECTED_SOURCE_B : vérifier la solution.', encoding='utf-8')
        (self.folder / 'Autre.txt').write_text('UNSELECTED_SOURCE', encoding='utf-8')
        self.teacher = User.objects.create_user(
            username='resources-teacher', email='resources-teacher@example.test', role='teacher',
        )
        TeacherProfile.objects.get_or_create(user=self.teacher)
        session = self.client.session
        session['user_id'] = self.teacher.pk
        session.save()
        self.url = reverse('quizzes:teacher_ai')
        self.payload = {
            'niveau': course.niveau, 'lesson': self.lesson.pk, 'question_count': 1,
            'seconds_per_question': 35, 'difficulty': 'moyen', 'action': 'generate',
            'generation_mode': 'resources', 'resource_selection_present': '1',
            'description': 'TEACHER_FOCUS : deux étapes puis vérification.',
        }

    def choices(self):
        return resource_catalog(Lesson.objects.filter(pk=self.lesson.pk).select_related('course').prefetch_related('resources'))[str(self.lesson.pk)]

    def test_multiple_selected_resources_and_upload_are_combined_without_hidden_sources(self):
        context, warnings, names = prepare_resources(
            self.choices(), ['Règles.txt', 'Méthodes.txt'], [upload(text='UPLOADED_SOURCE')],
        )
        for marker in ('SELECTED_SOURCE_A', 'SELECTED_SOURCE_B', 'UPLOADED_SOURCE'):
            self.assertIn(marker, context)
        self.assertNotIn('UNSELECTED_SOURCE', context)
        self.assertNotIn('HIDDEN_LESSON_CONTENT', context)
        self.assertEqual(names, ['Consignes.txt'])
        self.assertEqual(warnings, [])
        self.assertFalse((self.media / 'Consignes.txt').exists())

    @patch.object(AIService, '_get_provider', return_value=SimpleNamespace(name='test', model='test'))
    @patch.object(AIService, '_chat', return_value=json.dumps(QUIZ_DATA))
    def test_form_reaches_actual_ai_transport_with_resources_description_and_related_knowledge(self, chat, provider):
        with patch.object(Lesson, 'get_ai_help', side_effect=AssertionError('Hidden content must not be read')):
            response = self.client.post(self.url, {
                **self.payload, 'source_files': ['Règles.txt', 'Méthodes.txt'],
                'resource_uploads': [upload(text='UPLOADED_SOURCE')],
            })
        self.assertContains(response, 'Quiz généré avec succès.')
        prompt = chat.call_args_list[0].args[0][1]['content']
        for marker in ('SELECTED_SOURCE_A', 'SELECTED_SOURCE_B', 'UPLOADED_SOURCE', 'TEACHER_FOCUS'):
            self.assertIn(marker, prompt)
        self.assertIn('Tu peux compléter', prompt)
        self.assertIn('jamais sortir du niveau scolaire', prompt)
        self.assertNotIn('seule source', prompt)
        self.assertNotIn('strictement dans le contenu', prompt)
        self.assertNotIn('UNSELECTED_SOURCE', prompt)
        self.assertNotIn('HIDDEN_LESSON_CONTENT', prompt)
        self.assertEqual(Quiz.objects.get().created_by, self.teacher)
        self.assertEqual(Quiz.objects.get().seconds_per_question, 35)
        self.assertEqual(response.context['selected_source_files'], ['Règles.txt', 'Méthodes.txt'])
        self.assertContains(response, 'sélectionnez à nouveau ces fichiers')

    @patch.object(AIService, '_get_provider', return_value=SimpleNamespace(name='test', model='test'))
    @patch.object(AIService, '_chat', return_value=json.dumps(QUIZ_DATA))
    def test_difficult_mode_does_not_reintroduce_document_only_restriction(self, chat, provider):
        AIService().generate_quiz_from_lesson(
            self.lesson, 1, 'difficile', resource_context='SELECTED_RESOURCE',
            description='Évaluer des applications liées aux équations.',
            allow_related_knowledge=True,
        )
        prompt = chat.call_args_list[0].args[0][1]['content']
        self.assertIn('DIFFICULTÉ DIFFICILE', prompt)
        self.assertIn('SELECTED_RESOURCE', prompt)
        self.assertNotIn('strictement sur le contenu fourni', prompt)
        self.assertIn('connaissances mathématiques liées', prompt)

    @patch.object(AIService, 'generate_quiz_from_lesson', return_value=QUIZ_DATA)
    def test_no_resources_uses_description_not_implicit_lesson_sources(self, generate):
        response = self.client.post(self.url, self.payload)
        self.assertContains(response, 'Quiz généré avec succès.')
        kwargs = generate.call_args.kwargs
        self.assertFalse(kwargs['use_resources'])
        self.assertEqual(kwargs['resource_context'], '')
        self.assertTrue(kwargs['allow_related_knowledge'])
        self.assertIn('TEACHER_FOCUS', kwargs['description'])

    @patch.object(AIService, 'generate_quiz_from_lesson', return_value=QUIZ_DATA)
    def test_upload_only_generation(self, generate):
        response = self.client.post(self.url, {
            **self.payload, 'description': '', 'resource_uploads': [upload()],
        })
        self.assertContains(response, 'Quiz généré avec succès.')
        self.assertTrue(generate.call_args.kwargs['use_resources'])
        self.assertIn('isoler x', generate.call_args.kwargs['resource_context'])

    @patch.object(AIService, 'generate_quiz_from_lesson', return_value=QUIZ_DATA)
    def test_topic_mode_ignores_selected_files_and_uploads(self, generate):
        response = self.client.post(self.url, {
            **self.payload, 'generation_mode': 'topic', 'subject': 'Équations',
            'source_files': ['missing.txt'], 'resource_uploads': [upload('bad.exe')],
        })
        self.assertContains(response, 'Quiz généré avec succès.')
        self.assertEqual(generate.call_args.kwargs['resource_context'], '')
        self.assertFalse(generate.call_args.kwargs['use_resources'])

    @patch.object(AIService, 'generate_quiz_from_lesson')
    def test_no_resources_and_no_instructions_is_rejected_before_ai(self, generate):
        response = self.client.post(self.url, {**self.payload, 'description': ''})
        self.assertContains(response, 'Sans ressources, indiquez un sujet ou une description')
        generate.assert_not_called()
        self.assertFalse(Quiz.objects.exists())

    @patch.object(AIService, 'generate_quiz_from_lesson')
    def test_foreign_missing_and_traversal_selections_fail_without_partial_generation(self, generate):
        for value in ('../Règles.txt', '/tmp/file.txt', 'resource:999999', 'missing.txt'):
            response = self.client.post(self.url, {
                **self.payload, 'source_files': ['Règles.txt', value],
            })
            self.assertContains(response, 'introuvable pour cette leçon')
        generate.assert_not_called()
        self.assertFalse(Quiz.objects.exists())

    @patch.object(AIService, 'generate_quiz_from_lesson')
    def test_invalid_upload_keeps_form_parameters_and_never_saves_partial_quiz(self, generate):
        response = self.client.post(self.url, {
            **self.payload, 'source_files': ['Règles.txt'], 'resource_uploads': [upload('script.exe')],
        })
        self.assertContains(response, 'format non accepté')
        self.assertEqual(response.context['selected_source_files'], ['Règles.txt'])
        self.assertEqual(response.context['quiz_description'], self.payload['description'])
        self.assertEqual(response.context['selected_seconds_per_question'], 35)
        generate.assert_not_called()
        self.assertFalse(Quiz.objects.exists())

    def test_catalog_includes_course_exercises_db_resources_and_lesson_pdf(self):
        course_folder = self.folder.parent / 'Cours'
        course_folder.mkdir()
        (course_folder / 'Cours.md').write_text('COURS_MARKER', encoding='utf-8')
        (course_folder / 'Document.pdf').write_bytes(pdf_bytes())
        exercise_folder = self.folder.parent / 'Exercices'
        exercise_folder.mkdir()
        (exercise_folder / 'TD.pdf').write_bytes(pdf_bytes())
        (self.folder / 'Escape.txt').symlink_to(course_folder / 'Cours.md')
        resource = Resources.objects.create(
            lesson=self.lesson, name='Fiche', file=upload('Fiche.txt', 'DB_RESOURCE_MARKER'),
        )
        self.lesson.pdf.save('Lesson.pdf', SimpleUploadedFile('Lesson.pdf', pdf_bytes()))
        choices = self.choices()
        self.assertIn('cours:Cours.md', choices)
        self.assertIn('cours:Document.pdf', choices)
        self.assertIn('exercices:TD.pdf', choices)
        self.assertIn('lesson-pdf', choices)
        self.assertNotIn('Escape.txt', choices)
        context, _, _ = prepare_resources(choices, [f'resource:{resource.pk}', 'cours:Cours.md'], [])
        self.assertIn('DB_RESOURCE_MARKER', context)
        self.assertIn('COURS_MARKER', context)

    def test_pdf_docx_and_unicode_text_are_extracted(self):
        for name, content, marker in (
            ('Cours.pdf', pdf_bytes(), 'PDF_SELECTED_MARKER'),
            ('Fiche.docx', docx_bytes('DOCX_MARKER $2x=6$'), 'DOCX_MARKER'),
            ('Texte.md', 'قاعدة $x^2$'.encode(), 'قاعدة $x^2$'),
        ):
            with self.subTest(name=name):
                text, _, _ = extract_document(BytesIO(content), name)
                self.assertIn(marker, text)

    def test_empty_corrupt_and_image_only_documents_fail_explicitly(self):
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        blank_pdf = BytesIO()
        writer.write(blank_pdf)
        for name, content in (
            ('Empty.txt', b''), ('Encoding.txt', b'\xff'), ('Binary.txt', b'abc\x00'),
            ('Corrupt.pdf', b'not a PDF'), ('Corrupt.docx', b'not a ZIP'),
            ('Scan.pdf', blank_pdf.getvalue()),
        ):
            with self.subTest(name=name), self.assertRaises(ValueError):
                extract_document(BytesIO(content), name)
        with self.assertRaisesMessage(ValueError, 'OCR'):
            extract_document(BytesIO(blank_pdf.getvalue()), 'Scan.pdf')

    def test_docx_xml_entities_are_rejected(self):
        handle = BytesIO()
        with ZipFile(handle, 'w') as archive:
            archive.writestr('word/document.xml', b'<!DOCTYPE x [<!ENTITY a "unsafe">]><x>&a;</x>')
        with self.assertRaisesMessage(ValueError, 'non autorisée'):
            extract_document(BytesIO(handle.getvalue()), 'Unsafe.docx')

    def test_upload_and_combined_count_and_size_limits(self):
        with self.assertRaisesMessage(ValueError, '5 fichiers'):
            prepare_resources(self.choices(), [], [upload(f'{n}.txt') for n in range(6)])
        with self.assertRaisesMessage(ValueError, '12 ressources'):
            prepare_resources(self.choices(), [str(n) for n in range(13)], [])
        with patch('quizzes.resources.MAX_FILE_BYTES', 4):
            with self.assertRaisesMessage(ValueError, '10 Mo'):
                prepare_resources(self.choices(), [], [upload(text='too long')])
        with patch('quizzes.resources.MAX_TOTAL_BYTES', 4):
            with self.assertRaisesMessage(ValueError, '25 Mo'):
                prepare_resources(self.choices(), [], [upload(text='too long')])

    @override_settings(QUIZ_LESSON_CONTEXT_CHARS=500)
    def test_context_budget_keeps_every_source_and_warns_about_excerpts(self):
        context, warnings, _ = prepare_resources(
            {}, [], [upload('A.txt', 'A_MARKER ' + 'x' * 2000), upload('B.txt', 'B_MARKER ' + 'y' * 2000)],
        )
        self.assertLessEqual(len(context), 500)
        self.assertIn('A_MARKER', context)
        self.assertIn('B_MARKER', context)
        self.assertEqual(len(warnings), 2)

    @patch.object(AIService, 'generate_quiz_from_lesson')
    def test_student_cannot_upload_or_generate(self, generate):
        student = User.objects.create_user(
            username='resources-student', email='resources-student@example.test', role='student',
        )
        session = self.client.session
        session['user_id'] = student.pk
        session.save()
        response = self.client.post(self.url, {**self.payload, 'resource_uploads': [upload()]})
        self.assertEqual(response.status_code, 302)
        generate.assert_not_called()

    @patch.object(AIService, 'generate_quiz_from_lesson', side_effect=ValueError('Provider unavailable'))
    def test_provider_failure_does_not_persist_quiz_or_upload(self, generate):
        response = self.client.post(self.url, {
            **self.payload, 'resource_uploads': [upload('Private.txt', 'PRIVATE_MARKER')],
        })
        self.assertContains(response, 'Provider unavailable')
        self.assertFalse(Quiz.objects.exists())
        self.assertEqual(len(list(self.media.rglob('Private.txt'))), 0)

    def test_form_exposes_multiple_uploads_and_selection(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'enctype="multipart/form-data"')
        self.assertContains(response, 'name="source_files"')
        self.assertContains(response, 'name="resource_uploads"')
        self.assertIn('Règles.txt', [
            item['value'] for item in response.context['resource_options_by_lesson'][str(self.lesson.pk)]
        ])

    @patch.object(AIService, 'generate_quiz_from_lesson')
    def test_invalid_lesson_and_numeric_parameters_never_raise_server_errors(self, generate):
        for payload in (
            {'lesson': 'invalid'}, {'question_count': 'not-a-number'},
            {'seconds_per_question': 'NaN'},
        ):
            with self.subTest(payload=payload):
                response = self.client.post(self.url, {**self.payload, **payload})
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context['error'])
        self.assertEqual(self.client.get(self.url, {'lesson': 'invalid'}).status_code, 200)
        generate.assert_not_called()
