"""Phase 1 : modèles, droits, moteur d'opérations et API REST."""
import threading
import uuid

from django.db import connection
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from accounts.models import User
from classrooms.models import Classroom

from . import operations
from .models import WhiteboardDocument, WhiteboardOperation, WhiteboardSnapshot
from .operations import apply_operations


def op_id():
    return uuid.uuid4().hex


def add(oid, page='page-1', **props):
    return {'op_id': op_id(), 'kind': 'object.add', 'page': page,
            'object': {'id': oid, 'type': 'rect', 'left': 10, 'top': 10, 'width': 50, 'height': 30, **props}}


class Base(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(username='prof', email='prof@ex.test', password='x', role='teacher')
        self.other_teacher = User.objects.create_user(username='prof2', email='prof2@ex.test', password='x',
                                                      role='teacher')
        self.student = User.objects.create_user(username='eleve', email='eleve@ex.test', password='x', role='student')
        self.classmate = User.objects.create_user(username='camarade', email='cam@ex.test', password='x',
                                                  role='student')
        self.outsider = User.objects.create_user(username='autre', email='autre@ex.test', password='x',
                                                 role='student')
        self.classroom = Classroom.objects.create(name='1bac1', niveau='1bac_sm', teacher=self.teacher)
        self.classroom.add_member(self.student)
        self.classroom.add_member(self.classmate)
        other_class = Classroom.objects.create(name='TC2', niveau='tronc_commun', teacher=self.other_teacher)
        other_class.add_member(self.outsider)
        self.clients = {}

    def client_for(self, user):
        if user.pk not in self.clients:
            client = Client()
            session = client.session
            session['user_id'] = user.pk
            session['password_session_version'] = user.password_session_version
            session.save()
            self.clients[user.pk] = client
        return self.clients[user.pk]

    def api(self, user, method, name, data=None, **kwargs):
        url = reverse(f'mathboard:{name}', kwargs=kwargs)
        client = self.client_for(user)
        if method == 'get':
            return client.get(url, data or {})
        return getattr(client, method)(url, data or {}, content_type='application/json')

    def create(self, user=None, **data):
        response = self.api(user or self.teacher, 'post', 'api_documents', {'title': 'Fonctions', **data})
        self.assertEqual(response.status_code, 201, response.content)
        return WhiteboardDocument.objects.get(pk=response.json()['id'])

    def ops(self, user, document, ops):
        return self.api(user, 'post', 'api_operations', {'client_id': 'c1', 'ops': ops}, pk=document.pk)


class DocumentAccessTests(Base):
    def test_create_has_first_page_and_owner_manages(self):
        document = self.create(level='1bac_sm', chapter='Limites')
        state = self.api(self.teacher, 'get', 'api_state', pk=document.pk).json()
        self.assertEqual(state['access'], 'manage')
        self.assertEqual([p['uid'] for p in state['pages']], ['page-1'])
        self.assertEqual(state['document']['chapter'], 'Limites')

    def test_sharing_only_with_own_classroom(self):
        self.create(classroom=self.classroom.pk)
        response = self.api(self.other_teacher, 'post', 'api_documents',
                            {'title': 'X', 'classroom': self.classroom.pk})
        self.assertEqual(response.status_code, 403)
        response = self.api(self.student, 'post', 'api_documents', {'title': 'X', 'classroom': self.classroom.pk})
        self.assertEqual(response.status_code, 403)

    def test_visibility_follows_classes_and_members(self):
        shared = self.create(classroom=self.classroom.pk)
        private = self.create(title='Privé')
        own = self.create(self.student, title='Mon brouillon')
        titles = lambda u: {d['title'] for d in self.api(u, 'get', 'api_documents').json()}  # noqa: E731
        self.assertEqual(titles(self.student), {'Fonctions', 'Mon brouillon'})
        self.assertEqual(titles(self.outsider), set())
        self.assertEqual(self.api(self.outsider, 'get', 'api_state', pk=shared.pk).status_code, 404)
        self.assertEqual(self.api(self.student, 'get', 'api_state', pk=private.pk).status_code, 404)
        self.assertEqual(self.api(self.student, 'get', 'api_state', pk=own.pk).json()['access'], 'manage')
        self.assertEqual(self.api(self.student, 'get', 'api_state', pk=shared.pk).json()['access'], 'view')

    def test_only_owner_deletes_and_only_manager_edits_settings(self):
        document = self.create(classroom=self.classroom.pk)
        self.assertEqual(self.api(self.student, 'patch', 'api_document', {'title': 'Pirate'},
                                  pk=document.pk).status_code, 403)
        self.assertEqual(self.api(self.teacher, 'patch', 'api_document', {'students_can_edit': True},
                                  pk=document.pk).json()['students_can_edit'], True)
        self.assertEqual(self.api(self.student, 'delete', 'api_document', pk=document.pk).status_code, 403)
        self.assertEqual(self.api(self.teacher, 'delete', 'api_document', pk=document.pk).status_code, 204)

    def test_requires_login_and_csrf(self):
        self.assertIn(Client().get(reverse('mathboard:api_documents')).status_code, (401, 403))
        strict = Client(enforce_csrf_checks=True)
        session = strict.session
        session['user_id'] = self.teacher.pk
        session['password_session_version'] = self.teacher.password_session_version
        session.save()
        response = strict.post(reverse('mathboard:api_documents'), {'title': 'X'}, content_type='application/json')
        self.assertEqual(response.status_code, 403)
        self.assertIn('CSRF', response.json()['detail'])


class OperationTests(Base):
    def setUp(self):
        super().setUp()
        self.document = self.create(classroom=self.classroom.pk)

    def test_add_update_delete_with_revisions(self):
        response = self.ops(self.teacher, self.document, [add('r1'), add('r2')])
        self.assertEqual(response.json()['revision'], 2)
        self.assertEqual([r['status'] for r in response.json()['results']], ['accepted', 'accepted'])
        upd = {'op_id': op_id(), 'kind': 'object.update', 'page': 'page-1', 'id': 'r1', 'props': {'left': 99}}
        dele = {'op_id': op_id(), 'kind': 'object.delete', 'page': 'page-1', 'id': 'r2'}
        self.assertEqual(self.ops(self.teacher, self.document, [upd, dele]).json()['revision'], 4)
        objects = self.api(self.teacher, 'get', 'api_state', pk=self.document.pk).json()['pages'][0]['objects']
        self.assertEqual(set(objects), {'r1'})
        self.assertEqual(objects['r1']['left'], 99)
        self.assertEqual(objects['r1']['_by'], self.teacher.pk)
        self.assertEqual(objects['r1']['_rev'], 3)
        self.assertEqual(WhiteboardOperation.objects.filter(document=self.document).count(), 4)

    def test_resent_operation_is_not_applied_twice(self):
        op = add('r1')
        self.ops(self.teacher, self.document, [op])
        again = self.ops(self.teacher, self.document, [op, op]).json()
        self.assertEqual([r['status'] for r in again['results']], ['duplicate', 'duplicate'])
        self.assertEqual(again['revision'], 1)

    def test_conflicts_are_explicit(self):
        self.ops(self.teacher, self.document, [add('r1')])
        results = self.ops(self.teacher, self.document, [
            add('r1'),
            {'op_id': op_id(), 'kind': 'object.delete', 'page': 'page-1', 'id': 'r1'},
            {'op_id': op_id(), 'kind': 'object.update', 'page': 'page-1', 'id': 'r1', 'props': {'left': 1}},
        ]).json()['results']
        self.assertEqual([(r['status'], r.get('code')) for r in results],
                         [('rejected', 'conflict'), ('accepted', None), ('rejected', 'conflict')])

    def test_concurrent_updates_merge_by_property_and_flag_stale(self):
        self.ops(self.teacher, self.document, [add('r1')])
        self.ops(self.teacher, self.document, [
            {'op_id': op_id(), 'kind': 'object.update', 'page': 'page-1', 'id': 'r1', 'props': {'left': 5},
             'base_rev': 1}])
        self.ops(self.teacher, self.document, [
            {'op_id': op_id(), 'kind': 'object.update', 'page': 'page-1', 'id': 'r1', 'props': {'fill': 'red'},
             'base_rev': 1}])
        obj = self.api(self.teacher, 'get', 'api_state', pk=self.document.pk).json()['pages'][0]['objects']['r1']
        self.assertEqual((obj['left'], obj['fill']), (5, 'red'))
        stale = WhiteboardOperation.objects.get(document=self.document, revision=3).payload['stale']
        self.assertTrue(stale)

    def test_students_need_permission_and_only_touch_their_objects(self):
        self.ops(self.teacher, self.document, [add('prof-obj')])
        self.assertEqual(self.ops(self.student, self.document, [add('s1')]).status_code, 403)
        self.document.students_can_edit = True
        self.document.save()
        self.assertEqual(self.ops(self.student, self.document, [add('s1')]).json()['results'][0]['status'],
                         'accepted')
        results = self.ops(self.student, self.document, [
            {'op_id': op_id(), 'kind': 'object.delete', 'page': 'page-1', 'id': 'prof-obj'},
            {'op_id': op_id(), 'kind': 'object.update', 'page': 'page-1', 'id': 's1', 'props': {'top': 3}},
            {'op_id': op_id(), 'kind': 'page.delete', 'page': 'page-1'},
        ]).json()['results']
        self.assertEqual([(r['status'], r.get('code')) for r in results],
                         [('rejected', 'forbidden'), ('accepted', None), ('rejected', 'forbidden')])
        # Le professeur gère tout, y compris les objets des élèves.
        self.assertEqual(self.ops(self.teacher, self.document, [
            {'op_id': op_id(), 'kind': 'object.delete', 'page': 'page-1', 'id': 's1'}]).json()['results'][0][
            'status'], 'accepted')
        self.assertEqual(self.ops(self.outsider, self.document, [add('x')]).status_code, 404)

    def test_object_validation(self):
        bad = [
            {'op_id': op_id(), 'kind': 'object.add', 'page': 'page-1', 'object': {'id': 'a', 'type': 'script'}},
            add('b c'),
            {'op_id': op_id(), 'kind': 'object.add', 'page': 'page-1',
             'object': {'id': 'img', 'type': 'image', 'src': 'https://evil.example/x.png'}},
            {'op_id': op_id(), 'kind': 'object.add', 'page': 'page-1',
             'object': {'id': 'm', 'type': 'math', 'latex': r'\href{javascript:alert(1)}{x}'}},
            {'op_id': op_id(), 'kind': 'object.add', 'page': 'page-1',
             'object': {'id': 'big', 'type': 'path', 'path': 'M' * (400 * 1024)}},
            {'op_id': op_id(), 'kind': 'object.add', 'page': 'absente', 'object': {'id': 'z', 'type': 'rect'}},
            {'op_id': op_id(), 'kind': 'inconnu'},
            {'kind': 'object.add'},
        ]
        results = self.ops(self.teacher, self.document, bad).json()['results']
        self.assertTrue(all(r['status'] == 'rejected' for r in results), results)
        good = [
            {'op_id': op_id(), 'kind': 'object.add', 'page': 'page-1',
             'object': {'id': 'm', 'type': 'math', 'latex': r'\frac{1}{x}+\sqrt{2}', '_by': 999}},
            {'op_id': op_id(), 'kind': 'object.add', 'page': 'page-1',
             'object': {'id': 'img', 'type': 'image', 'src': 'data:image/png;base64,iVBORw0KGgo='}},
        ]
        self.assertEqual([r['status'] for r in self.ops(self.teacher, self.document, good).json()['results']],
                         ['accepted', 'accepted'])
        obj = self.api(self.teacher, 'get', 'api_state', pk=self.document.pk).json()['pages'][0]['objects']['m']
        self.assertEqual(obj['_by'], self.teacher.pk)  # « _by » ne peut pas être imposé par le client
        self.assertEqual(self.ops(self.teacher, self.document, [add(f'o{i}') for i in range(201)]).status_code, 400)

    def test_pages_add_move_delete(self):
        results = self.ops(self.teacher, self.document, [
            {'op_id': op_id(), 'kind': 'page.add', 'page': {'uid': 'p2', 'title': 'Exercice', 'background': 'grid'}},
            {'op_id': op_id(), 'kind': 'page.add', 'page': {'uid': 'p3', 'background': 'axes'}, 'index': 0},
            {'op_id': op_id(), 'kind': 'page.move', 'page': 'p2', 'index': 0},
            {'op_id': op_id(), 'kind': 'page.update', 'page': 'p2', 'props': {'title': 'Ex. 1'}},
            {'op_id': op_id(), 'kind': 'page.add', 'page': {'uid': 'p4', 'background': 'nope'}},
        ]).json()['results']
        self.assertEqual([r['status'] for r in results], ['accepted'] * 4 + ['rejected'])
        pages = self.api(self.teacher, 'get', 'api_state', pk=self.document.pk).json()['pages']
        self.assertEqual([(p['uid'], p['title'], p['position']) for p in pages],
                         [('p2', 'Ex. 1', 0), ('p3', '', 1), ('page-1', '', 2)])
        self.ops(self.teacher, self.document, [add('x', page='p3')])
        for uid in ('p2', 'p3'):
            self.ops(self.teacher, self.document, [{'op_id': op_id(), 'kind': 'page.delete', 'page': uid}])
        last = self.ops(self.teacher, self.document, [{'op_id': op_id(), 'kind': 'page.delete', 'page': 'page-1'}])
        self.assertEqual(last.json()['results'][0]['status'], 'rejected')

    def test_since_returns_missing_operations_or_reset(self):
        self.ops(self.teacher, self.document, [add('a'), add('b'), add('c')])
        since = self.api(self.student, 'get', 'api_operations', {'since': 1}, pk=self.document.pk).json()
        self.assertFalse(since['reset'])
        self.assertEqual([o['revision'] for o in since['ops']], [2, 3])
        self.assertEqual(since['ops'][0]['object']['id'], 'b')
        self.assertTrue(self.api(self.student, 'get', 'api_operations', {'since': 99},
                                 pk=self.document.pk).json()['reset'])
        self.assertEqual(self.api(self.student, 'get', 'api_operations', {'since': 3},
                                  pk=self.document.pk).json()['ops'], [])


class SnapshotTests(Base):
    def test_manual_snapshot_and_restore(self):
        document = self.create()
        self.ops(self.teacher, document, [add('a')])
        snap = self.api(self.teacher, 'post', 'api_snapshots', {'label': 'Avant exercice'}, pk=document.pk).json()
        self.assertEqual(snap['revision'], 1)
        self.ops(self.teacher, document, [add('b'), {'op_id': op_id(), 'kind': 'object.delete',
                                                     'page': 'page-1', 'id': 'a'}])
        response = self.api(self.teacher, 'post', 'api_snapshot_restore', pk=document.pk, snapshot_id=snap['id'])
        self.assertEqual(response.json()['revision'], 4)
        state = self.api(self.teacher, 'get', 'api_state', pk=document.pk).json()
        self.assertEqual(set(state['pages'][0]['objects']), {'a'})
        kinds = list(WhiteboardSnapshot.objects.filter(document=document).values_list('kind', flat=True))
        self.assertIn(WhiteboardSnapshot.KIND_BEFORE_RESTORE, kinds)
        self.assertTrue(self.api(self.teacher, 'get', 'api_operations', {'since': 3}, pk=document.pk).json()['reset'])
        # Lecture seule : on consulte les versions sans pouvoir restaurer.
        document.classroom = self.classroom
        document.save()
        self.assertEqual(self.api(self.student, 'get', 'api_snapshots', pk=document.pk).status_code, 200)
        self.assertEqual(self.api(self.student, 'post', 'api_snapshot_restore', pk=document.pk,
                                  snapshot_id=snap['id']).status_code, 403)

    def test_automatic_snapshots_are_taken_and_pruned(self):
        document = self.create()
        old_every, old_keep = operations.AUTO_SNAPSHOT_EVERY, operations.AUTO_SNAPSHOT_KEEP
        operations.AUTO_SNAPSHOT_EVERY, operations.AUTO_SNAPSHOT_KEEP = 2, 3
        try:
            for i in range(12):
                self.ops(self.teacher, document, [add(f'o{i}')])
        finally:
            operations.AUTO_SNAPSHOT_EVERY, operations.AUTO_SNAPSHOT_KEEP = old_every, old_keep
        autos = WhiteboardSnapshot.objects.filter(document=document, kind='auto')
        self.assertEqual(autos.count(), 3)
        self.assertEqual(max(autos.values_list('revision', flat=True)), 12)


class MemberTests(Base):
    def test_invitations_follow_existing_classes(self):
        document = self.create()
        ok = self.api(self.teacher, 'post', 'api_members', {'username': 'eleve', 'role': 'editor'}, pk=document.pk)
        self.assertEqual(ok.status_code, 201)
        self.assertEqual(self.api(self.teacher, 'post', 'api_members', {'username': 'autre'},
                                  pk=document.pk).status_code, 400)
        self.assertEqual(self.api(self.teacher, 'post', 'api_members', {'username': 'prof2', 'role': 'manager'},
                                  pk=document.pk).status_code, 201)
        self.assertEqual(self.api(self.student, 'get', 'api_state', pk=document.pk).json()['access'], 'edit')
        self.assertEqual(self.api(self.other_teacher, 'get', 'api_state', pk=document.pk).json()['access'], 'manage')
        self.assertEqual(self.api(self.student, 'get', 'api_members', pk=document.pk).status_code, 403)
        member_id = ok.json()['id']
        self.api(self.teacher, 'patch', 'api_member', {'role': 'viewer'}, pk=document.pk, member_id=member_id)
        self.assertEqual(self.api(self.student, 'get', 'api_state', pk=document.pk).json()['access'], 'view')
        self.api(self.teacher, 'delete', 'api_member', pk=document.pk, member_id=member_id)
        self.assertEqual(self.api(self.student, 'get', 'api_state', pk=document.pk).status_code, 404)

    def test_student_owner_invites_classmates_only(self):
        document = self.create(self.student, title='Groupe')
        self.assertEqual(self.api(self.student, 'post', 'api_members', {'username': 'camarade', 'role': 'editor'},
                                  pk=document.pk).status_code, 201)
        self.assertEqual(self.api(self.student, 'post', 'api_members', {'username': 'autre'},
                                  pk=document.pk).status_code, 400)


@override_settings(REST_FRAMEWORK={'DEFAULT_THROTTLE_RATES': {'mathboard_ops': '100000/min'}})
class ConcurrencyTests(TransactionTestCase):
    """Écritures simultanées : révisions uniques et aucune opération perdue.

    Significatif sur PostgreSQL (verrou de ligne) ; SQLite sérialise déjà les écritures.
    """

    def test_parallel_batches_get_distinct_revisions(self):
        if connection.vendor != 'postgresql':
            self.skipTest('Vérifié sur PostgreSQL.')
        teacher = User.objects.create_user(username='p', email='p@ex.test', password='x', role='teacher')
        document = WhiteboardDocument.objects.create(title='T', owner=teacher)
        document.pages.create(uid='page-1')
        errors = []

        def worker(n):
            try:
                for i in range(10):
                    apply_operations(document, teacher, [add(f'w{n}-{i}')])
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                connection.close()

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        document.refresh_from_db()
        self.assertEqual(document.revision, 60)
        self.assertEqual(sorted(WhiteboardOperation.objects.filter(document=document)
                                .values_list('revision', flat=True)), list(range(1, 61)))
        self.assertEqual(len(document.pages.get().content), 60)
