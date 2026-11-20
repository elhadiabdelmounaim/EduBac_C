"""Fonctions de classe : travail à rendre et correction, notifications, mode
présentation, participation, images en fichiers, conversion des anciens
tableaux, entretien, assistant IA désactivé, alertes d'erreurs."""
import base64
import io
import json
import logging
import os
import shutil
import tempfile
import time
import uuid
from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.core.files.storage import default_storage
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from accounts.models import User
from classrooms.models import Classroom
from notifications.models import Notification
from whiteboard.models import WhiteboardBoard

from .access import access_level, visible_documents
from .images import storage_name
from .models import WhiteboardDocument, WhiteboardOperation, WhiteboardPage, WhiteboardSnapshot


def login(user):
    client = Client()
    session = client.session
    session['user_id'] = user.pk
    session['password_session_version'] = user.password_session_version
    session.save()
    return client


def post(client, url, data=None):
    return client.post(url, json.dumps(data or {}), content_type='application/json')


def png_bytes(size=(40, 30), color=(200, 30, 30)):
    out = io.BytesIO()
    Image.new('RGB', size, color).save(out, 'PNG')
    return out.getvalue()


class Base(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(username='prof', email='p@ex.test', password='x', role='teacher',
                                                first_name='Karim', last_name='Prof')
        self.other_teacher = User.objects.create_user(username='prof2', email='p2@ex.test', password='x', role='teacher')
        self.student = User.objects.create_user(username='salma', email='s@ex.test', password='x', role='student',
                                                first_name='Salma', last_name='Élève')
        self.classmate = User.objects.create_user(username='omar', email='o@ex.test', password='x', role='student',
                                                  first_name='Omar', last_name='Camarade')
        self.outsider = User.objects.create_user(username='autre', email='a@ex.test', password='x', role='student')
        self.classroom = Classroom.objects.create(name='1bac1', niveau='1bac_sm', teacher=self.teacher)
        self.classroom.add_member(self.student)
        self.classroom.add_member(self.classmate)
        self.subject = WhiteboardDocument.objects.create(title='Devoir limites', owner=self.teacher,
                                                         classroom=self.classroom, accepts_submissions=True)
        WhiteboardPage.objects.create(document=self.subject, uid='page-1', content={
            'enonce': {'id': 'enonce', 'type': 'i-text', 'text': 'Calculer la limite', '_by': self.teacher.pk, '_rev': 1}})

    def ops(self, client, document, *ops):
        payload = [{'op_id': uuid.uuid4().hex, 'page': 'page-1', **op} for op in ops]
        return post(client, reverse('mathboard:api_operations', args=[document.pk]), {'client_id': 'c', 'ops': payload})

    def make_copy(self, student=None):
        response = post(login(student or self.student), reverse('mathboard:api_copy', args=[self.subject.pk]))
        self.assertIn(response.status_code, (200, 201), response.content)
        return WhiteboardDocument.objects.get(pk=response.json()['id'])


class SubmissionTests(Base):
    def test_copy_contains_the_subject_and_is_private_until_submitted(self):
        copy = self.make_copy()
        self.assertEqual(copy.source, self.subject)
        self.assertEqual(copy.submission_status, 'draft')
        self.assertIn('enonce', copy.pages.get().content)
        self.assertIsNone(copy.classroom)
        # Une seule copie par élève : le second appel renvoie la même.
        again = post(login(self.student), reverse('mathboard:api_copy', args=[self.subject.pk]))
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.json()['id'], copy.pk)
        self.assertEqual(access_level(self.student, copy), 'manage')
        self.assertIsNone(access_level(self.teacher, copy))          # brouillon : privé
        self.assertIsNone(access_level(self.classmate, copy))
        self.assertNotIn(copy, visible_documents(self.teacher))
        self.assertEqual(self.ops(login(self.teacher), copy, {'kind': 'object.delete', 'id': 'enonce'}).status_code, 404)

    def test_copy_only_for_assignments_and_not_for_the_teacher(self):
        self.subject.accepts_submissions = False
        self.subject.save()
        self.assertEqual(post(login(self.student), reverse('mathboard:api_copy', args=[self.subject.pk])).status_code, 400)
        self.subject.accepts_submissions = True
        self.subject.save()
        self.assertEqual(post(login(self.teacher), reverse('mathboard:api_copy', args=[self.subject.pk])).status_code, 400)
        self.assertEqual(post(login(self.outsider), reverse('mathboard:api_copy', args=[self.subject.pk])).status_code, 404)

    def test_submit_correct_return_and_redo(self):
        copy = self.make_copy()
        student = login(self.student)
        self.assertEqual(self.ops(student, copy, {'kind': 'object.add', 'object': {
            'id': 'rep', 'type': 'i-text', 'text': 'lim = 2', 'left': 1, 'top': 1}}).status_code, 200)
        self.assertEqual(post(login(self.classmate), reverse('mathboard:api_submit', args=[copy.pk])).status_code, 404)
        response = post(student, reverse('mathboard:api_submit', args=[copy.pk]))
        self.assertEqual(response.status_code, 200, response.content)
        copy.refresh_from_db()
        self.assertEqual(copy.submission_status, 'submitted')
        self.assertTrue(Notification.objects.filter(recipient=self.teacher, title='Travail rendu').exists())
        # Rendu : l'élève ne modifie plus, le professeur corrige sur la copie.
        self.assertEqual(access_level(self.student, copy), 'view')
        self.assertEqual(self.ops(student, copy, {'kind': 'object.delete', 'id': 'rep'}).status_code, 403)
        self.assertEqual(post(student, reverse('mathboard:api_submit', args=[copy.pk])).status_code, 400)  # déjà rendu
        teacher = login(self.teacher)
        self.assertIn(copy, visible_documents(self.teacher))
        self.assertEqual(self.ops(teacher, copy, {'kind': 'object.add', 'object': {
            'id': 'corr', 'type': 'i-text', 'text': 'Très bien', 'left': 5, 'top': 5, 'fill': '#e03131'}}).status_code, 200)
        self.assertEqual(post(login(self.other_teacher), reverse('mathboard:api_correct', args=[copy.pk]),
                              {'grade': '20'}).status_code, 404)
        response = post(teacher, reverse('mathboard:api_correct', args=[copy.pk]),
                        {'action': 'return', 'grade': '17/20', 'feedback': 'Bonne méthode.'})
        self.assertEqual(response.status_code, 200, response.content)
        copy.refresh_from_db()
        self.assertEqual((copy.submission_status, copy.grade, copy.feedback), ('returned', '17/20', 'Bonne méthode.'))
        note = Notification.objects.get(recipient=self.student, title='Travail corrigé')
        self.assertIn('17/20', note.message)
        self.assertEqual(note.link, reverse('mathboard:editor', args=[copy.pk]))
        # Reprise demandée : l'élève peut de nouveau écrire.
        post(teacher, reverse('mathboard:api_correct', args=[copy.pk]), {'action': 'redo', 'feedback': 'Justifier.'})
        copy.refresh_from_db()
        self.assertEqual(copy.submission_status, 'draft')
        self.assertEqual(access_level(self.student, copy), 'manage')
        self.assertTrue(Notification.objects.filter(recipient=self.student, title='Travail à reprendre').exists())
        self.assertEqual(copy.snapshots.filter(kind='manual').count(), 3)

    def test_copies_overview_lists_every_student(self):
        copy = self.make_copy()
        post(login(self.student), reverse('mathboard:api_submit', args=[copy.pk]))
        data = login(self.teacher).get(reverse('mathboard:api_copies', args=[self.subject.pk])).json()
        rows = {r['name']: r for r in data['rows']}
        self.assertEqual(rows['Salma Élève']['status'], 'submitted')
        self.assertEqual(rows['Salma Élève']['copy'], copy.pk)
        self.assertEqual(rows['Omar Camarade']['status'], 'none')
        self.assertEqual(login(self.student).get(reverse('mathboard:api_copies', args=[self.subject.pk])).status_code, 403)

    def test_copy_cannot_be_shared(self):
        copy = self.make_copy()
        client = login(self.student)
        url = reverse('mathboard:api_document', args=[copy.pk])
        self.assertEqual(client.patch(url, json.dumps({'students_can_edit': True}), content_type='application/json').status_code, 400)
        self.assertEqual(post(client, reverse('mathboard:api_members', args=[copy.pk]),
                              {'username': 'omar', 'role': 'viewer'}).status_code, 400)
        self.assertEqual(client.patch(url, json.dumps({'title': 'Ma copie'}), content_type='application/json').status_code, 200)

    def test_list_page_sections(self):
        copy = self.make_copy()
        post(login(self.student), reverse('mathboard:api_submit', args=[copy.pk]))
        page = login(self.teacher).get(reverse('mathboard:list')).content.decode()
        self.assertIn('Travaux à corriger', page)
        self.assertIn(reverse('mathboard:editor', args=[copy.pk]), page)
        page = login(self.student).get(reverse('mathboard:list')).content.decode()
        self.assertIn('Mes travaux', page)


class NotificationTests(Base):
    def test_sharing_with_a_class_notifies_its_students(self):
        client = login(self.teacher)
        response = post(client, reverse('mathboard:api_documents'), {'title': 'Cours', 'classroom': self.classroom.pk})
        self.assertEqual(response.status_code, 201)
        for student in (self.student, self.classmate):
            self.assertTrue(Notification.objects.filter(recipient=student, title='Tableau mathématique partagé').exists())
        self.assertFalse(Notification.objects.filter(recipient=self.outsider).exists())

    def test_turning_on_assignment_notifies_once_per_change(self):
        document = WhiteboardDocument.objects.create(title='Exercice', owner=self.teacher, classroom=self.classroom)
        url = reverse('mathboard:api_document', args=[document.pk])
        client = login(self.teacher)
        client.patch(url, json.dumps({'chapter': 'Limites'}), content_type='application/json')
        self.assertFalse(Notification.objects.filter(recipient=self.student).exists())
        client.patch(url, json.dumps({'accepts_submissions': True}), content_type='application/json')
        self.assertEqual(Notification.objects.filter(recipient=self.student, title='Travail à rendre').count(), 1)

    def test_invited_member_is_notified(self):
        document = WhiteboardDocument.objects.create(title='Brouillon', owner=self.teacher)
        post(login(self.teacher), reverse('mathboard:api_members', args=[document.pk]), {'username': 'salma', 'role': 'editor'})
        self.assertTrue(Notification.objects.filter(recipient=self.student, title='Invitation à un tableau').exists())


class PreparedDocumentTests(Base):
    """Créer un tableau pour une classe sans le partager tout de suite."""

    def test_prepared_document_stays_hidden_until_shared(self):
        teacher = login(self.teacher)
        response = post(teacher, reverse('mathboard:api_documents'),
                        {'title': 'Séance 4', 'classroom': self.classroom.pk, 'class_visible': False})
        self.assertEqual(response.status_code, 201)
        document = WhiteboardDocument.objects.get(pk=response.json()['id'])
        self.assertFalse(document.class_visible)
        # Aucune alerte, aucun accès, rien dans la liste des élèves.
        self.assertFalse(Notification.objects.filter(recipient=self.student).exists())
        self.assertIsNone(access_level(self.student, document))
        self.assertNotIn(document, visible_documents(self.student))
        student = login(self.student)
        self.assertEqual(student.get(reverse('mathboard:api_document', args=[document.pk])).status_code, 404)
        self.assertNotContains(student.get(reverse('mathboard:list')), 'Séance 4')
        # Le professeur le voit, marqué « non partagé », et peut le préparer.
        self.assertEqual(access_level(self.teacher, document), 'manage')
        self.assertContains(teacher.get(reverse('mathboard:list')), 'Préparé · non partagé')
        self.assertEqual(self.ops(teacher, document, {'kind': 'add', 'object_id': 'a',
                                                      'data': {'type': 'i-text', 'text': 'x'}}).status_code, 200)
        # Partage : les élèves sont prévenus une seule fois et y ont accès.
        url = reverse('mathboard:api_document', args=[document.pk])
        teacher.patch(url, json.dumps({'class_visible': True}), content_type='application/json')
        teacher.patch(url, json.dumps({'chapter': 'Limites'}), content_type='application/json')
        self.assertEqual(Notification.objects.filter(recipient=self.student, title='Tableau mathématique partagé').count(), 1)
        document.refresh_from_db()
        self.assertEqual(access_level(self.student, document), 'view')
        self.assertEqual(student.get(url).status_code, 200)

    def test_prepared_assignment_cannot_be_copied_yet(self):
        self.subject.class_visible = False
        self.subject.save()
        response = post(login(self.student), reverse('mathboard:api_copy', args=[self.subject.pk]))
        self.assertIn(response.status_code, (403, 404))
        self.assertFalse(WhiteboardDocument.objects.filter(source=self.subject).exists())

    def test_without_the_field_sharing_stays_immediate(self):
        response = post(login(self.teacher), reverse('mathboard:api_documents'),
                        {'title': 'Cours', 'classroom': self.classroom.pk})
        self.assertTrue(response.json()['class_visible'])


class PresentationTests(Base):
    def test_presenter_view_reaches_followers_through_polling(self):
        url = reverse('mathboard:api_presentation', args=[self.subject.pk])
        view = {'page': 'page-1', 'cx': 120, 'cy': 80, 'w': 800, 'h': 500}
        self.assertEqual(post(login(self.student), url, view).status_code, 403)
        response = post(login(self.teacher), url, view)
        self.assertEqual(response.status_code, 200, response.content)
        ops_url = reverse('mathboard:api_operations', args=[self.subject.pk]) + '?since=0'
        data = login(self.student).get(ops_url).json()
        self.assertEqual(data['presentation']['cx'], 120)
        self.assertEqual(data['presentation']['name'], 'Karim Prof')
        self.assertNotIn('at', data['presentation'])
        # La présentation ne change ni la révision ni la date de modification.
        before = WhiteboardDocument.objects.get(pk=self.subject.pk)
        self.assertEqual(before.revision, 0)
        # Sans signal pendant 90 s : terminée.
        with mock.patch('time.time', return_value=time.time() + 120):
            self.assertIsNone(login(self.student).get(ops_url).json()['presentation'])
        self.assertEqual(login(self.teacher).delete(url).status_code, 204)
        self.assertIsNone(login(self.student).get(ops_url).json()['presentation'])

    def test_invalid_views_are_refused(self):
        url = reverse('mathboard:api_presentation', args=[self.subject.pk])
        client = login(self.teacher)
        self.assertEqual(post(client, url, {'page': 'inconnue', 'cx': 0, 'cy': 0, 'w': 100, 'h': 100}).status_code, 400)
        self.assertEqual(post(client, url, {'page': 'page-1', 'cx': 'nan', 'cy': 0, 'w': 100, 'h': 100}).status_code, 400)

    def test_settings_fingerprint_changes_when_work_is_handed_in(self):
        copy = self.make_copy()
        url = reverse('mathboard:api_operations', args=[copy.pk]) + '?since=0'
        client = login(self.student)
        before = client.get(url).json()['settings']
        post(client, reverse('mathboard:api_submit', args=[copy.pk]))
        self.assertNotEqual(client.get(url).json()['settings'], before)


class ContributionsTests(Base):
    def test_counts_by_author(self):
        self.subject.students_can_edit = True
        self.subject.save()
        self.ops(login(self.student), self.subject,
                 {'kind': 'object.add', 'object': {'id': 'a1', 'type': 'rect', 'left': 0, 'top': 0}},
                 {'kind': 'object.add', 'object': {'id': 'a2', 'type': 'rect', 'left': 9, 'top': 0}})
        rows = login(self.teacher).get(reverse('mathboard:api_contributions', args=[self.subject.pk])).json()
        by_name = {r['name']: r for r in rows}
        self.assertEqual(by_name['Salma Élève']['objects'], 2)
        self.assertEqual(by_name['Salma Élève']['operations'], 2)
        self.assertEqual(by_name['Karim Prof']['objects'], 1)
        self.assertTrue(rows[0]['is_owner'])
        self.assertEqual(login(self.student).get(reverse('mathboard:api_contributions', args=[self.subject.pk])).status_code, 403)


class HandwritingTests(Base):
    """Écriture manuscrite → texte et formules (service externe simulé)."""

    LINES = {'unreadable': False, 'lines': [
        {'segments': [{'kind': 'text', 'content': '  Soit  '}, {'kind': 'math', 'content': 'f(x)=x^2'}]},
        {'segments': [{'kind': 'text', 'content': 'الدالة'}, {'kind': 'math', 'content': 'f'}, {'kind': 'text', 'content': 'متزايدة'}]},
        {'segments': [{'kind': 'math', 'content': ''}, {'kind': 'bad', 'content': 'x'}]},
    ]}

    def url(self, document=None):
        return reverse('mathboard:api_handwriting', args=[(document or self.subject).pk])

    def image(self):
        return 'data:image/png;base64,' + base64.b64encode(png_bytes(size=(300, 120), color=(255, 255, 255))).decode()

    def test_disabled_by_default(self):
        self.assertEqual(post(login(self.teacher), self.url(), {'image': self.image()}).status_code, 404)
        response = login(self.teacher).get(reverse('mathboard:editor', args=[self.subject.pk]))
        self.assertNotContains(response, 'data-act="convert"')
        self.assertNotContains(response, 'mb-ink.js')

    @override_settings(MATHBOARD_HANDWRITING_ENABLED=True, ANTHROPIC_API_KEY='test')
    def test_teacher_gets_clean_lines(self):
        with mock.patch('mathboard.handwriting._ask_claude', return_value=self.LINES) as ask:
            response = post(login(self.teacher), self.url(), {'image': self.image()})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['lines'], [
            {'segments': [{'kind': 'text', 'content': 'Soit'}, {'kind': 'math', 'content': 'f(x)=x^2'}]},
            {'segments': [{'kind': 'text', 'content': 'الدالة'}, {'kind': 'math', 'content': 'f'},
                          {'kind': 'text', 'content': 'متزايدة'}]},
        ])
        self.assertEqual(ask.call_args[0][0][:8], b'\x89PNG\r\n\x1a\n')    # seule l'image est transmise
        page = login(self.teacher).get(reverse('mathboard:editor', args=[self.subject.pk]))
        self.assertContains(page, 'data-act="convert"')
        self.assertContains(page, 'mb-ink.js')

    @override_settings(MATHBOARD_HANDWRITING_ENABLED=True, ANTHROPIC_API_KEY='test')
    def test_reserved_to_teachers_with_edit_access(self):
        document = WhiteboardDocument.objects.create(title='Libre', owner=self.student)
        with mock.patch('mathboard.handwriting._ask_claude', return_value=self.LINES) as ask:
            self.assertEqual(post(login(self.student), self.url(document), {'image': self.image()}).status_code, 403)
            self.assertEqual(post(login(self.other_teacher), self.url(), {'image': self.image()}).status_code, 404)
        ask.assert_not_called()
        page = login(self.student).get(reverse('mathboard:editor', args=[document.pk]))
        self.assertNotContains(page, 'data-act="convert"')

    @override_settings(MATHBOARD_HANDWRITING_ENABLED=True, ANTHROPIC_API_KEY='test')
    def test_bad_images_and_illegible_writing(self):
        teacher = login(self.teacher)
        jpeg = io.BytesIO()
        Image.new('RGB', (20, 20)).save(jpeg, 'JPEG')
        with mock.patch('mathboard.handwriting._ask_claude', return_value={'lines': [], 'unreadable': True}):
            for image in (None, 'data:image/png;base64,@@@', 'data:image/png;base64,' + base64.b64encode(jpeg.getvalue()).decode()):
                self.assertEqual(post(teacher, self.url(), {'image': image}).status_code, 400)
            response = post(teacher, self.url(), {'image': self.image()})
        self.assertEqual(response.status_code, 400)
        self.assertIn('illisible', response.json()['detail'])

    @override_settings(MATHBOARD_HANDWRITING_ENABLED=True, ANTHROPIC_API_KEY='test')
    def test_large_selection_is_reduced_before_sending(self):
        big = 'data:image/png;base64,' + base64.b64encode(png_bytes(size=(3200, 800))).decode()
        with mock.patch('mathboard.handwriting._ask_claude', return_value=self.LINES) as ask:
            post(login(self.teacher), self.url(), {'image': big})
        self.assertEqual(max(Image.open(io.BytesIO(ask.call_args[0][0])).size), 1568)

    @override_settings(MATHBOARD_HANDWRITING_ENABLED=True, ANTHROPIC_API_KEY='test')
    def test_missing_package_gives_a_clear_message(self):
        import builtins
        real_import = builtins.__import__

        def no_anthropic(name, *args, **kwargs):
            if name == 'anthropic':
                raise ImportError(name)
            return real_import(name, *args, **kwargs)
        with mock.patch('builtins.__import__', side_effect=no_anthropic), self.assertLogs('mathboard.handwriting', 'ERROR'):
            response = post(login(self.teacher), self.url(), {'image': self.image()})
        self.assertEqual(response.status_code, 400)
        self.assertIn('pas installée', response.json()['detail'])


class HandwritingRequestTests(TestCase):
    """Requête envoyée au SDK Anthropic (module simulé : le paquet est facultatif)."""

    def fake_sdk(self, response=None, error=None):
        import sys
        import types
        sdk = types.ModuleType('anthropic')

        class APIStatusError(Exception):
            status_code, message = 500, 'boom'

        class RateLimitError(APIStatusError):
            pass

        class APIConnectionError(Exception):
            pass
        sdk.APIStatusError, sdk.RateLimitError, sdk.APIConnectionError = APIStatusError, RateLimitError, APIConnectionError
        calls = []

        class Messages:
            def create(self, **kwargs):
                calls.append(kwargs)
                if error:
                    raise getattr(sdk, error)()
                return response

        class Client:
            def __init__(self, **kwargs):
                calls.append(kwargs)
                self.beta = types.SimpleNamespace(messages=Messages())
        sdk.Anthropic = Client
        return mock.patch.dict(sys.modules, {'anthropic': sdk}), calls

    @staticmethod
    def reply(text, stop='end_turn'):
        from types import SimpleNamespace as NS
        return NS(stop_reason=stop, content=[NS(type='thinking'), NS(type='text', text=text)])

    @override_settings(ANTHROPIC_API_KEY='cle-test', MATHBOARD_HANDWRITING_MODEL='claude-opus-5-5')
    def test_request_shape_and_answer(self):
        from .handwriting import OUTPUT_SCHEMA, _ask_claude
        patch, calls = self.fake_sdk(self.reply('{"lines": [], "unreadable": true}'))
        with patch:
            self.assertEqual(_ask_claude(b'PNG'), {'lines': [], 'unreadable': True})
        client, request = calls
        self.assertEqual(client['api_key'], 'cle-test')
        self.assertEqual(request['model'], 'claude-opus-5-5')
        self.assertEqual(request['betas'], ['server-side-fallback-2026-07-01'])
        self.assertEqual(request['fallbacks'], 'default')
        self.assertEqual(request['output_config'], {'effort': 'low', 'format': {'type': 'json_schema', 'schema': OUTPUT_SCHEMA}})
        image = request['messages'][0]['content'][0]
        self.assertEqual((image['type'], image['source']['media_type'], image['source']['data']), ('image', 'image/png', 'UE5H'))

    @override_settings(ANTHROPIC_API_KEY='cle-test')
    def test_refusals_and_errors_become_french_messages(self):
        from .handwriting import HandwritingError, _ask_claude
        cases = [(self.reply('', 'refusal'), None, 'refusé'), (self.reply('{', 'max_tokens'), None, 'trop longue'),
                 (self.reply('pas du json'), None, 'inattendue'), (None, 'RateLimitError', 'saturé'),
                 (None, 'APIConnectionError', 'injoignable')]
        for response, error, expected in cases:
            patch, _ = self.fake_sdk(response, error)
            with patch, self.assertRaisesMessage(HandwritingError, expected):
                _ask_claude(b'PNG')
        patch, _ = self.fake_sdk(None, 'APIStatusError')
        with patch, self.assertLogs('mathboard.handwriting', 'ERROR'), self.assertRaisesMessage(HandwritingError, 'erreur'):
            _ask_claude(b'PNG')


class ImageUploadTests(Base):
    def setUp(self):
        super().setUp()
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)
        super().tearDown()

    def upload(self, user, content, name='image.png'):
        from django.core.files.uploadedfile import SimpleUploadedFile
        return login(user).post(reverse('mathboard:api_images', args=[self.subject.pk]),
                                {'image': SimpleUploadedFile(name, content, content_type='image/png')})

    def test_image_is_stored_as_a_file_and_usable_on_the_board(self):
        response = self.upload(self.teacher, png_bytes())
        self.assertEqual(response.status_code, 201, response.content)
        src = response.json()['src']
        self.assertRegex(src, rf'^/tableau-maths/{self.subject.pk}/images/[0-9a-f]{{32}}\.png$')
        self.assertTrue(os.path.exists(os.path.join(self.media, 'mathboard', str(self.subject.pk), src.rsplit('/', 1)[1])))
        added = self.ops(login(self.teacher), self.subject,
                         {'kind': 'object.add', 'object': {'id': 'img', 'type': 'image', 'src': src, 'left': 0, 'top': 0}})
        self.assertEqual(added.json()['results'][0]['status'], 'accepted')

    def test_image_is_served_only_to_people_who_can_open_the_board(self):
        src = self.upload(self.teacher, png_bytes()).json()['src']
        response = login(self.teacher).get(src)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/png')
        self.assertIn('private', response['Cache-Control'])
        self.assertEqual(b''.join(response.streaming_content)[:8], b'\x89PNG\r\n\x1a\n')
        self.assertEqual(login(self.student).get(src).status_code, 200)       # élève de la classe
        self.assertEqual(login(self.outsider).get(src).status_code, 404)      # hors de la classe
        self.assertEqual(Client().get(src).status_code, 302)                   # non connecté
        # La copie de l'élève garde l'accès aux images du sujet, même s'il est retiré.
        self.make_copy()
        self.subject.class_visible = False
        self.subject.save()
        self.assertEqual(login(self.student).get(src).status_code, 200)
        self.assertEqual(login(self.classmate).get(src).status_code, 404)
        bad = src.rsplit('/', 1)[0] + '/../../settings.py'
        self.assertEqual(login(self.teacher).get(bad).status_code, 404)

    def test_large_images_are_reduced_and_bad_files_refused(self):
        response = self.upload(self.teacher, png_bytes(size=(3000, 1000)))
        self.assertEqual((response.json()['width'], response.json()['height']), (1600, 533))
        self.assertEqual(self.upload(self.teacher, b'<svg onload=alert(1)>', 'x.png').status_code, 400)
        self.assertEqual(self.upload(self.student, png_bytes()).status_code, 403)  # lecture seule


class LegacyConversionTests(Base):
    def setUp(self):
        super().setUp()
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()
        image = 'data:image/png;base64,' + base64.b64encode(png_bytes((20, 10))).decode()
        self.board = WhiteboardBoard.objects.create(title='Ancien cours', created_by=self.teacher,
                                                    classroom=self.classroom, content={
            'version': 1, 'background': 'ruled', 'objects': [
                {'id': 's1', 'type': 'stroke', 'color': '#e03131', 'size': 3,
                 'points': [{'x': 10, 'y': 10}, {'x': 50, 'y': 30}], 'by': self.student.pk},
                {'id': 'g', 'type': 'stroke', 'erase': True, 'size': 20, 'points': [{'x': 0, 'y': 0}]},
                {'id': 'r', 'type': 'rect', 'x': 100, 'y': 100, 'w': 60, 'h': 40, 'color': '#1971c2', 'size': 2},
                {'id': 'c', 'type': 'circle', 'cx': 300, 'cy': 200, 'r': 30, 'color': '#000', 'size': 2},
                {'id': 'a', 'type': 'arrow', 'x1': 0, 'y1': 0, 'x2': 100, 'y2': 0, 'color': '#000', 'size': 2},
                {'id': 't', 'type': 'text', 'text': 'الدالة f', 'x': 10, 'y': 300, 'color': '#000', 'size': 3},
                {'id': 'm', 'type': 'math', 'latex': '\\frac{1}{x}', 'x': 400, 'y': 50},
                {'id': 'gr', 'type': 'graph', 'expr': 'x^2-1', 'x': 0, 'y': 400, 'w': 240, 'h': 180},
                {'id': 'p', 'type': 'plot', 'x': 500, 'y': 400, 'w': 560, 'h': 420,
                 'view': {'xmin': -3, 'xmax': 3, 'ymin': -2, 'ymax': 2},
                 'items': [{'line': 'f(x)=x^2-2'}, {'line': 'A=(1;2,5)'}, {'line': 'a=Curseur(-5;5;0,1)'}]},
                {'id': 'i', 'type': 'image', 'src': image, 'x': 600, 'y': 10, 'w': 40, 'h': 20},
                {'id': 'x', 'type': 'plotanswer', 'plot': 'p'},
            ]})

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)
        super().tearDown()

    def test_conversion_keeps_content_and_reports_what_is_skipped(self):
        response = login(self.teacher).post(reverse('mathboard:convert_legacy', args=[self.board.pk]))
        document = WhiteboardDocument.objects.get(legacy_board=self.board)
        self.assertRedirects(response, reverse('mathboard:editor', args=[document.pk]), fetch_redirect_response=False)
        self.assertEqual(document.classroom, self.classroom)
        page = document.pages.get()
        self.assertEqual(page.background, 'lines')
        objects = sorted(page.content.values(), key=lambda o: o['z'])
        self.assertEqual([o['type'] for o in objects],
                         ['path', 'rect', 'circle', 'path', 'i-text', 'math', 'geometry', 'geometry', 'image'])
        stroke = objects[0]
        self.assertEqual(stroke['_by'], self.student.pk)                  # l'auteur d'origine est gardé
        self.assertEqual(stroke['path'][0], ['M', 10.0, 10.0])
        self.assertEqual(objects[4]['direction'], 'rtl')                  # texte arabe
        self.assertEqual(objects[6]['script'], 'f(x) = x^2-1')
        self.assertEqual(objects[7]['script'], 'f(x)=x^2-2\nA=(1,2.5)\n# a=Curseur(-5;5;0,1)')
        self.assertRegex(objects[8]['src'], r'^/tableau-maths/\d+/images/[0-9a-f]{32}\.png$')
        self.assertAlmostEqual(objects[8]['scaleX'], 2.0)
        flash = [str(m) for m in response.wsgi_request._messages]
        self.assertIn('9 élément(s)', flash[0])
        self.assertIn('1 gomme', flash[0])
        self.assertIn('1 plotanswer', flash[0])
        # Deuxième clic : on retrouve la même conversion. L'ancien tableau est intact.
        again = login(self.teacher).post(reverse('mathboard:convert_legacy', args=[self.board.pk]))
        self.assertRedirects(again, reverse('mathboard:editor', args=[document.pk]), fetch_redirect_response=False)
        self.board.refresh_from_db()
        self.assertEqual(len(self.board.content['objects']), 11)

    def test_only_the_author_converts(self):
        self.assertEqual(login(self.other_teacher).post(reverse('mathboard:convert_legacy', args=[self.board.pk])).status_code, 404)
        self.assertEqual(login(self.teacher).get(reverse('mathboard:convert_legacy', args=[self.board.pk])).status_code, 405)

    def test_management_command(self):
        out = io.StringIO()
        call_command('mathboard_convert_legacy', '--all', stdout=out)
        self.assertIn('1 tableau(x) converti(s)', out.getvalue())
        call_command('mathboard_convert_legacy', '--all', stdout=out)
        self.assertIn('déjà converti', out.getvalue())


class CleanupTests(Base):
    def setUp(self):
        super().setUp()
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)
        super().tearDown()

    def test_old_operations_are_pruned_but_recent_ones_kept(self):
        document = self.subject
        old = timezone.now() - timedelta(days=30)
        WhiteboardOperation.objects.bulk_create([
            WhiteboardOperation(document=document, revision=r, op_id=f'o{r}', kind='object.update', payload={})
            for r in range(1, 2501)])
        WhiteboardOperation.objects.filter(document=document, revision__lte=2400).update(created_at=old)
        WhiteboardDocument.objects.filter(pk=document.pk).update(revision=2500)
        call_command('mathboard_cleanup', stdout=io.StringIO())
        remaining = WhiteboardOperation.objects.filter(document=document)
        self.assertEqual(remaining.order_by('revision').first().revision, 501)
        self.assertEqual(remaining.count(), 2000)

    def test_embedded_images_move_to_files_and_unused_files_are_removed(self):
        data = 'data:image/png;base64,' + base64.b64encode(png_bytes()).decode()
        page = self.subject.pages.get()
        page.content['img'] = {'id': 'img', 'type': 'image', 'src': data, '_by': self.teacher.pk}
        page.save()
        WhiteboardSnapshot.objects.create(document=self.subject, revision=0, data={'pages': [
            {'uid': 'page-1', 'objects': {'img': {'id': 'img', 'type': 'image', 'src': data}}}]})
        orphan = default_storage.save('mathboard/999/vieux.png', io.BytesIO(png_bytes()))
        os.utime(os.path.join(self.media, orphan), (time.time() - 3 * 86400,) * 2)
        recent = default_storage.save('mathboard/999/recent.png', io.BytesIO(png_bytes()))
        out = io.StringIO()
        call_command('mathboard_cleanup', stdout=out)
        self.assertIn('images déplacées vers media/ : 2', out.getvalue())
        page.refresh_from_db()
        src = page.content['img']['src']
        self.assertTrue(src.startswith(f'/tableau-maths/{self.subject.pk}/images/'))
        self.assertTrue(default_storage.exists(storage_name(src)))
        self.assertFalse(default_storage.exists(orphan))
        self.assertTrue(default_storage.exists(recent))


class AssistantDisabledTests(Base):
    def test_ai_is_off_by_default(self):
        client = login(self.teacher)
        response = post(client, reverse('mathboard:api_ai', args=[self.subject.pk, 'hint']), {'question': 'q'})
        self.assertEqual(response.status_code, 404)
        page = client.get(reverse('mathboard:editor', args=[self.subject.pk])).content.decode()
        self.assertNotIn('mbAiBtn', page)
        self.assertNotIn('mbAiPanel', page)
        self.assertNotIn('contexte de l’assistant', page)
        with override_settings(MATHBOARD_AI_ENABLED=True):
            page = client.get(reverse('mathboard:editor', args=[self.subject.pk])).content.decode()
        self.assertIn('mbAiBtn', page)


class ErrorAlertTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_user(username='admin', email='ad@ex.test', password='x', role='teacher',
                                              is_staff=True, is_superuser=True)

    def report(self, **data):
        body = {'message': 'TypeError: x is undefined', 'source': 'http://testserver/static/js/a.js', 'line': 12,
                'page': 'http://testserver/tableau-maths/3/', **data}
        return self.client.post('/erreurs-client/', json.dumps(body), content_type='application/json',
                                HTTP_ORIGIN='http://testserver')

    def test_browser_error_notifies_admins_once_per_hour(self):
        self.assertEqual(self.report().status_code, 204)
        self.report()
        notes = Notification.objects.filter(recipient=self.admin, title='Erreur dans le navigateur')
        self.assertEqual(notes.count(), 1)
        self.assertIn('TypeError: x is undefined', notes.get().message)
        self.assertIn('/tableau-maths/3/', notes.get().message)

    def test_noise_and_other_sites_are_ignored(self):
        self.report(message='ResizeObserver loop limit exceeded')
        self.report(source='chrome-extension://abc/x.js')
        self.client.post('/erreurs-client/', json.dumps({'message': 'm'}), content_type='application/json',
                         HTTP_ORIGIN='https://evil.example')
        self.assertFalse(Notification.objects.exists())

    def test_server_error_notifies_admins(self):
        try:
            raise ZeroDivisionError('division')
        except ZeroDivisionError:
            logging.getLogger('django.request').error('Internal Server Error: /x/', exc_info=True,
                                                      extra={'status_code': 500})
        note = Notification.objects.get(recipient=self.admin)
        self.assertEqual(note.title, 'Erreur du serveur')
        self.assertIn('ZeroDivisionError', note.message)
