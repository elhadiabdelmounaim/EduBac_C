"""Phases 3 à 8 côté serveur : calcul exact, présence, temps réel, export/import, IA."""
import json
import os
import socket
import threading
import time
import uuid
from unittest import mock

from asgiref.sync import async_to_sync
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from accounts.models import User
from classrooms.models import Classroom
from edubac_math import ParseError, compute, latex_to_text, parse

from . import ai_client, realtime
from .models import WhiteboardDocument, WhiteboardPage, WhiteboardSession


def login(client, user):
    session = client.session
    session['user_id'] = user.pk
    session['password_session_version'] = user.password_session_version
    session.save()
    return client


class SymbolicEngineTests(TestCase):
    """Phase 3 : analyseur sûr, conversion LaTeX et calculs SymPy."""

    def test_parser_never_executes_code(self):
        for evil in ('__import__("os").system("x")', 'x.__class__', "open('f')", 'a' * 700, 'x; y'):
            with self.assertRaises(ParseError):
                parse(evil)
        # Un mot inconnu n'est jamais appelé : c'est un produit de variables.
        self.assertEqual(str(parse('eval(1)')), 'E*a*l*v')

    def test_latex_conversion(self):
        self.assertEqual(str(parse(latex_to_text(r'\frac{x^{2}-1}{x-1}'))), '(x**2 - 1)/(x - 1)')
        self.assertEqual(latex_to_text(r'\begin{cases}x+y=2\\x-y=0\end{cases}'), 'x+y=2; x-y=0')
        self.assertEqual(str(parse(latex_to_text(r'\begin{pmatrix}1&2\\3&4\end{pmatrix}'))), 'Matrix([[1, 2], [3, 4]])')
        with self.assertRaises(ParseError):
            latex_to_text(r'\href{javascript:alert(1)}{x}')

    def test_calculations(self):
        cases = [
            ('factor', 'x^2-5x+6', {}, r'\left(x - 3\right) \left(x - 2\right)'),
            ('derivative', 'x^2 ln(x)', {}, r'x \left(2 \ln{\left(x \right)} + 1\right)'),
            ('integral', '2x+1', {'lower': '0', 'upper': '1'}, '2'),
            ('limit', 'sin(x)/x', {'point': '0'}, '1'),
            ('solve', 'x^2-4=0', {}, r'S = \left\{-2; 2\right\}'),
            ('solve', 'x+y=2; x-y=0', {}, r'\left(x, y\right) \in \left\{\left(1, 1\right)\right\}'),
            ('determinant', '[[1,2],[3,4]]', {}, '-2'),
        ]
        for action, expression, options, expected in cases:
            with self.subTest(action=action):
                result = compute(action, expression, **options)
                self.assertTrue(result['ok'], result)
                self.assertEqual(result['latex'], expected)

    def test_variations_and_asymptotes(self):
        table = compute('variations', 'x^3-3x')['table']
        self.assertEqual(table['points'], ['-\\infty', '-1', '1', '\\infty'])
        self.assertEqual(table['arrows'], ['up', 'down', 'up'])
        self.assertEqual([v['value'] for v in table['values']], ['-\\infty', '2', '-2', '\\infty'])
        forbidden = compute('variations', '1/x')['table']
        self.assertEqual(forbidden['forbidden'], ['0'])
        asym = compute('asymptotes', '(x^2+1)/(x-1)')
        self.assertEqual(asym['vertical'], ['1'])
        self.assertEqual(asym['oblique'][0]['slope'], 1.0)

    def test_errors_and_time_limit(self):
        self.assertIn('Une matrice est attendue', compute('determinant', 'x+1')['error'])
        self.assertIn('trop long', compute('simplify', '9^9^9', timeout=2)['error'])


class CalculApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='calc', email='c@ex.test', password='x', role='student')
        self.client = login(Client(), self.user)

    def test_latex_input_and_errors(self):
        url = reverse('mathboard:api_calcul')
        data = self.client.post(url, {'action': 'expand', 'latex': r'\left(x+1\right)^{2}'},
                                content_type='application/json').json()
        self.assertEqual(data['latex'], 'x^{2} + 2 x + 1')
        self.assertEqual(data['action_label'], 'Développer')
        bad = self.client.post(url, {'action': 'expand', 'latex': r'\unknown{x}'}, content_type='application/json')
        self.assertFalse(bad.json()['ok'])
        self.assertEqual(self.client.post(url, {'action': 'rm -rf'}, content_type='application/json').status_code, 400)
        self.assertIn(Client().post(url, {'action': 'expand'}, content_type='application/json').status_code, (401, 403))


class PresenceExportImportTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(username='p', email='p@ex.test', password='x', role='teacher')
        self.other = User.objects.create_user(username='o', email='o@ex.test', password='x', role='teacher')
        self.document = WhiteboardDocument.objects.create(title='Fonctions', owner=self.teacher, chapter='Limites')
        WhiteboardPage.objects.create(document=self.document, uid='page-1', background='axes', content={
            'm1': {'id': 'm1', 'type': 'math', 'latex': 'x^2', '_by': self.teacher.pk, '_rev': 1}})
        self.client = login(Client(), self.teacher)

    def test_presence_heartbeat(self):
        url = reverse('mathboard:api_presence', args=[self.document.pk])
        users = self.client.post(url, {'client_id': 'abc', 'page': 'page-1', 'cursor': {'x': 3, 'y': 4}},
                                 content_type='application/json').json()
        self.assertEqual([(u['client_id'], u['page'], u['cursor']) for u in users], [('abc', 'page-1', {'x': 3.0, 'y': 4.0})])
        self.document.members.create(user=self.other, role='viewer')
        hijack = login(Client(), self.other).post(url, {'client_id': 'abc'}, content_type='application/json')
        self.assertEqual(hijack.status_code, 403)
        self.client.delete(url + '?client_id=abc')
        self.assertFalse(WhiteboardSession.objects.exists())

    def test_export_import_roundtrip(self):
        exported = self.client.get(reverse('mathboard:api_export', args=[self.document.pk]))
        self.assertIn('attachment', exported['Content-Disposition'])
        data = exported.json()
        self.assertNotIn('_by', data['pages'][0]['objects']['m1'])
        importer = login(Client(), self.other)
        created = importer.post(reverse('mathboard:api_import'), {'data': data}, content_type='application/json')
        self.assertEqual(created.status_code, 201)
        copy = WhiteboardDocument.objects.get(pk=created.json()['id'])
        self.assertEqual((copy.owner, copy.title, copy.chapter), (self.other, 'Fonctions', 'Limites'))
        page = copy.pages.get()
        self.assertEqual(page.background, 'axes')
        self.assertEqual(page.content['m1']['_by'], self.other.pk)

    def test_import_rejects_invalid_files(self):
        url = reverse('mathboard:api_import')
        for data in ({'format': 'autre'}, {'format': 'edubac-mathboard', 'pages': []},
                     {'format': 'edubac-mathboard', 'pages': [{'objects': {
                         'x': {'type': 'image', 'src': 'https://evil.example/a.png'}}}]},
                     {'format': 'edubac-mathboard', 'pages': [{'objects': {'bad id': {'type': 'rect'}}}]}):
            self.assertEqual(self.client.post(url, {'data': data}, content_type='application/json').status_code, 400)
        self.assertEqual(WhiteboardDocument.objects.count(), 1)


@override_settings(MATHBOARD_AI_ENABLED=True, MATHBOARD_AI_URL='http://ai.internal', MATHBOARD_AI_TOKEN='jeton')
class AssistantProxyTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(username='p', email='p@ex.test', password='x', role='teacher')
        self.student = User.objects.create_user(username='s', email='s@ex.test', password='x', role='student')
        self.outsider = User.objects.create_user(username='z', email='z@ex.test', password='x', role='student')
        classroom = Classroom.objects.create(name='2bac', niveau='2bac_pc', teacher=self.teacher)
        classroom.add_member(self.student)
        self.document = WhiteboardDocument.objects.create(title='T', owner=self.teacher, classroom=classroom,
                                                          chapter='Logarithme')
        WhiteboardPage.objects.create(document=self.document, uid='page-1', content={
            'a': {'id': 'a', 'type': 'math', 'latex': r'\ln(x)'},
            'b': {'id': 'b', 'type': 'i-text', 'text': 'Étudier f'}})
        self.url = reverse('mathboard:api_ai', args=[self.document.pk, 'hint'])

    def test_payload_context_and_sanitized_answer(self):
        answer = {'reply': 'Indice', 'provider': 'mock', 'blocks': [
            {'type': 'math', 'content': r'\href{javascript:x}{y}'}, {'type': 'text', 'content': 'Pensez à ln.'},
            {'type': 'script', 'content': 'alert(1)'}]}
        with mock.patch.object(ai_client, '_post', return_value=(200, json.dumps(answer).encode())) as post:
            data = login(Client(), self.student).post(self.url, {'question': 'Aide ?', 'page': 'page-1'},
                                                      content_type='application/json').json()
        url, payload, headers, _ = post.call_args.args
        self.assertEqual(url, 'http://ai.internal/v1/hint')
        self.assertEqual(headers, {'X-Service-Token': 'jeton'})
        self.assertEqual((payload['level'], payload['chapter'], payload['role']), ('2bac_pc', 'Logarithme', 'student'))
        self.assertEqual(payload['board'], [{'type': 'math', 'content': r'\ln(x)'}, {'type': 'text', 'content': 'Étudier f'}])
        self.assertEqual([b['type'] for b in data['blocks']], ['text', 'text'])

    def test_errors(self):
        client = login(Client(), self.student)
        with mock.patch.object(ai_client, '_post', side_effect=OSError('down')):
            self.assertEqual(client.post(self.url, {'question': 'q'}, content_type='application/json').status_code, 502)
        self.assertEqual(client.post(reverse('mathboard:api_ai', args=[self.document.pk, 'pirate']), {'question': 'q'},
                                     content_type='application/json').status_code, 404)
        self.assertEqual(client.post(self.url, {}, content_type='application/json').status_code, 400)
        self.assertEqual(login(Client(), self.outsider).post(self.url, {'question': 'q'},
                                                              content_type='application/json').status_code, 404)
        with override_settings(MATHBOARD_AI_URL=''):
            response = client.post(self.url, {'question': 'q'}, content_type='application/json')
        self.assertEqual(response.status_code, 503)
        self.assertIn('pas encore configuré', response.json()['detail'])


def _free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


try:
    import fastapi  # noqa: F401
    import uvicorn  # noqa: F401
    HAS_AI_STACK = True
except ImportError:  # service IA non installé sur cette machine (ai_service/requirements.txt)
    HAS_AI_STACK = False


@__import__('unittest').skipUnless(HAS_AI_STACK, 'FastAPI/uvicorn non installés (ai_service/requirements.txt).')
@override_settings(MATHBOARD_AI_ENABLED=True)
class AssistantEndToEndTests(TestCase):
    """Django → service FastAPI réel (uvicorn), fournisseur « mock » : aucun appel externe."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import uvicorn
        from ai_service.app import app
        cls.env = mock.patch.dict(os.environ, {'AI_SERVICE_TOKEN': 'jeton-e2e', 'AI_PROVIDERS': 'mock'})
        cls.env.start()
        cls.port = _free_port()
        cls.server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=cls.port, log_level='warning'))
        cls.thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.thread.start()
        for _ in range(100):
            if cls.server.started:
                break
            time.sleep(0.05)

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(5)
        cls.env.stop()
        super().tearDownClass()

    def test_verify_goes_through_fastapi_and_sympy(self):
        teacher = User.objects.create_user(username='p', email='p@ex.test', password='x', role='teacher')
        document = WhiteboardDocument.objects.create(title='T', owner=teacher)
        WhiteboardPage.objects.create(document=document, uid='page-1')
        with override_settings(MATHBOARD_AI_URL=f'http://127.0.0.1:{self.port}', MATHBOARD_AI_TOKEN='jeton-e2e'):
            client = login(Client(), teacher)
            verify = client.post(reverse('mathboard:api_ai', args=[document.pk, 'verify']),
                                 {'student_answer': '(x+1)^2', 'expected': 'x^2+2x+1'},
                                 content_type='application/json').json()
            solve = client.post(reverse('mathboard:api_ai', args=[document.pk, 'solve']),
                                {'latex': 'x^{2}-9=0'}, content_type='application/json').json()
            with override_settings(MATHBOARD_AI_TOKEN='mauvais'):
                refused = client.post(reverse('mathboard:api_ai', args=[document.pk, 'hint']), {'question': 'q'},
                                      content_type='application/json')
        self.assertEqual(verify['verification']['correct'], True)
        self.assertEqual(verify['verification']['method'], 'sympy')
        self.assertEqual(solve['blocks'][1], {'type': 'math', 'content': r'S = \left\{-3; 3\right\}'})
        self.assertEqual(refused.status_code, 502)


class _ScopeUser:
    """Injecte l'utilisateur dans le scope (remplace l'authentification par session)."""

    def __init__(self, app, user):
        self.app, self.user = app, user

    async def __call__(self, scope, receive, send):
        return await self.app({**scope, 'user': self.user}, receive, send)


class RealtimeConsumerTests(TransactionTestCase):
    """Phase 5 : canal WebSocket (couche en mémoire ; Redis si REDIS_URL est défini)."""

    def setUp(self):
        self.teacher = User.objects.create_user(username='p', email='p@ex.test', password='x', role='teacher')
        self.student = User.objects.create_user(username='s', email='s@ex.test', password='x', role='student')
        self.outsider = User.objects.create_user(username='z', email='z@ex.test', password='x', role='student')
        self.classroom = Classroom.objects.create(name='TC', niveau='tronc_commun', teacher=self.teacher)
        self.classroom.add_member(self.student)
        self.document = WhiteboardDocument.objects.create(title='T', owner=self.teacher, classroom=self.classroom)
        WhiteboardPage.objects.create(document=self.document, uid='page-1')

    def communicator(self, user):
        from .routing import websocket_urlpatterns
        app = _ScopeUser(URLRouter(websocket_urlpatterns), user)
        return WebsocketCommunicator(app, f'/ws/tableau-maths/{self.document.pk}/',
                                     headers=[(b'origin', b'http://testserver')])

    def test_presence_cursors_ops_and_revocation(self):
        async def scenario():
            teacher, student = self.communicator(self.teacher), self.communicator(self.student)
            self.assertTrue((await teacher.connect())[0])
            self.assertTrue((await student.connect())[0])
            await teacher.send_json_to({'type': 'hello', 'client_id': 'ct', 'page': 'page-1'})
            presence = await teacher.receive_json_from(timeout=3)
            self.assertEqual(presence['type'], 'presence')
            await student.send_json_to({'type': 'hello', 'client_id': 'cs', 'page': 'page-1'})
            while True:
                message = await teacher.receive_json_from(timeout=3)
                if message['type'] == 'presence' and len(message['users']) == 2:
                    break
            await student.receive_json_from(timeout=3)  # présence (1)
            await student.receive_json_from(timeout=3)  # présence (2)
            # Curseur : reçu par l'autre, pas renvoyé à l'émetteur.
            await student.send_json_to({'type': 'cursor', 'x': 12, 'y': 34, 'page': 'page-1'})
            cursor = await teacher.receive_json_from(timeout=3)
            self.assertEqual((cursor['type'], cursor['client_id'], cursor['x']), ('cursor', 'cs', 12.0))
            self.assertTrue(await student.receive_nothing(timeout=0.3))
            # Opérations acceptées par l'API : diffusées à tous.
            await self._publish({'type': 'ops', 'revision': 1, 'ops': [{'kind': 'object.add', 'revision': 1}]})
            self.assertEqual((await student.receive_json_from(timeout=3))['revision'], 1)
            self.assertEqual((await teacher.receive_json_from(timeout=3))['revision'], 1)
            # Partage retiré : l'élève est déconnecté.
            await self._unshare()
            await self._publish({'type': 'document', 'document': {}})
            self.assertEqual((await student.receive_json_from(timeout=3))['type'], 'revoked')
            closed = await student.receive_output(timeout=3)
            self.assertEqual(closed['type'], 'websocket.close')
            self.assertEqual((await teacher.receive_json_from(timeout=3))['access'], 'manage')
            await teacher.disconnect()

        async_to_sync(scenario)()

    def test_outsider_and_anonymous_are_refused(self):
        async def scenario():
            for user in (self.outsider, None):
                connected, code = await self.communicator(user).connect()
                self.assertFalse(connected)
            evil = WebsocketCommunicator(_ScopeUser(URLRouter(__import__('mathboard.routing').routing.websocket_urlpatterns),
                                                    self.teacher), f'/ws/tableau-maths/{self.document.pk}/',
                                         headers=[(b'origin', b'https://evil.example')])
            self.assertFalse((await evil.connect())[0])

        async_to_sync(scenario)()

    async def _publish(self, message):
        from channels.db import database_sync_to_async
        await database_sync_to_async(realtime.publish)(self.document.pk, message)

    async def _unshare(self):
        from channels.db import database_sync_to_async

        def unshare():
            WhiteboardDocument.objects.filter(pk=self.document.pk).update(classroom=None)
        await database_sync_to_async(unshare)()


class OpIdTests(TestCase):
    def test_uuid_ids_are_accepted(self):
        teacher = User.objects.create_user(username='p', email='p@ex.test', password='x', role='teacher')
        document = WhiteboardDocument.objects.create(title='T', owner=teacher)
        WhiteboardPage.objects.create(document=document, uid='page-1')
        from .operations import apply_operations
        result = apply_operations(document, teacher, [{'op_id': uuid.uuid4().hex, 'kind': 'object.add', 'page': 'page-1',
                                                       'object': {'id': 'm' + uuid.uuid4().hex[:19], 'type': 'math',
                                                                  'latex': 'x'}}])
        self.assertEqual(result['results'][0]['status'], 'accepted')
