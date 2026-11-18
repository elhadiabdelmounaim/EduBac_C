import json

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from chat.models import ChatMessage, PrivateConversation, PrivateMessage
from classrooms.models import Classroom
from notifications.models import Notification

from .models import WhiteboardBoard, WhiteboardOp, WhiteboardPresence


def stroke(object_id, x=100, **extra):
    return {'id': object_id, 'type': 'stroke', 'color': '#000', 'size': 4,
            'points': [{'x': x, 'y': 100}, {'x': x + 20, 'y': 120}], **extra}


def text(object_id, x=100):
    return {'id': object_id, 'type': 'text', 'text': 'x = 2', 'x': x, 'y': 200, 'size': 4, 'color': '#000'}


@override_settings(ALLOWED_HOSTS=['testserver'])
class CollaborationTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create(username='prof', email='prof@t.test', role='teacher')
        self.student = User.objects.create(username='omar', email='omar@t.test', first_name='Omar')
        self.classmate = User.objects.create(username='salma', email='salma@t.test', first_name='Salma')
        self.outsider = User.objects.create(username='autre', email='autre@t.test')
        self.classroom = Classroom.objects.create(name='1BAC', teacher=self.teacher, niveau='tronc_commun')
        self.classroom.add_member(self.student)
        self.classroom.add_member(self.classmate)
        self.board = WhiteboardBoard.objects.create(
            title='Équations', created_by=self.teacher, classroom=self.classroom,
            content={'version': 1, 'objects': []},
        )

    def login(self, user):
        session = self.client.session
        session['user_id'] = user.pk
        session.save()

    def sync(self, user, ops=None, since=0, **extra):
        self.login(user)
        return self.client.post(
            reverse('whiteboard:sync', args=[self.board.pk]),
            json.dumps({'since': since, 'client': f'c{user.pk}', 'ops': ops or [], **extra}),
            content_type='application/json',
        )

    def post(self, user, name, payload):
        self.login(user)
        return self.client.post(reverse(f'whiteboard:{name}', args=[self.board.pk]),
                                json.dumps(payload), content_type='application/json')

    def objects(self):
        self.board.refresh_from_db()
        return {o['id']: o for o in self.board.content['objects']}

    def configure(self, **fields):
        WhiteboardBoard.objects.filter(pk=self.board.pk).update(**fields)
        self.board.refresh_from_db()

    # --- Synchronisation -------------------------------------------------
    def test_teacher_change_reaches_student_and_is_stamped_with_author(self):
        response = self.sync(self.teacher, [{'op': 'add', 'object': stroke('t1')}])
        self.assertEqual(response.json()['revision'], 1)
        self.assertEqual(self.objects()['t1']['by'], self.teacher.pk)
        seen = self.sync(self.student, since=0).json()
        self.assertEqual([op['op'] for op in seen['ops']], ['add'])
        self.assertEqual(seen['ops'][0]['object']['id'], 't1')
        self.assertEqual(self.sync(self.student, since=1).json()['ops'], [])

    def test_concurrent_additions_are_merged_not_overwritten(self):
        self.configure(students_can_edit=True)
        self.sync(self.teacher, [{'op': 'add', 'object': stroke('t1')}])
        self.sync(self.student, [{'op': 'add', 'object': stroke('s1', x=300)}], since=0)
        self.sync(self.classmate, [{'op': 'add', 'object': text('c1', x=500)}], since=0)
        self.assertEqual(set(self.objects()), {'t1', 's1', 'c1'})
        self.assertEqual(WhiteboardPresence.objects.get(board=self.board, user=self.student).contributions, 1)

    def test_old_revision_or_legacy_save_returns_the_full_content(self):
        self.sync(self.teacher, [{'op': 'add', 'object': stroke('t1')}])
        self.login(self.teacher)
        self.client.post(reverse('whiteboard:api_content', args=[self.board.pk]),
                         json.dumps({'content': {'version': 1, 'objects': [stroke('only')]}}),
                         content_type='application/json')
        data = self.sync(self.student, since=1).json()
        self.assertTrue(data['reset'])
        self.assertEqual([o['id'] for o in data['content']['objects']], ['only'])

    def test_legacy_objects_receive_stable_ids_on_load(self):
        self.configure(content={'version': 1, 'objects': [{'type': 'text', 'text': 'ancien', 'x': 1, 'y': 1}]})
        self.login(self.teacher)
        first = self.client.get(reverse('whiteboard:api_content', args=[self.board.pk])).json()
        again = self.client.get(reverse('whiteboard:api_content', args=[self.board.pk])).json()
        object_id = first['content']['objects'][0]['id']
        self.assertTrue(object_id.startswith('wb-'))
        self.assertEqual(again['content']['objects'][0]['id'], object_id)

    # --- Permissions -----------------------------------------------------
    def test_student_is_read_only_by_default(self):
        data = self.sync(self.student, [{'op': 'add', 'object': stroke('s1')}]).json()
        self.assertEqual(data['rejected'][0]['id'], 's1')
        self.assertEqual(self.objects(), {})
        self.assertFalse(data['state']['caps']['draw'])

    def test_each_permission_is_enforced_by_type(self):
        self.configure(students_can_edit=True, allow_draw=True, allow_text=False, allow_images=False)
        image = {'id': 'img', 'type': 'image', 'src': 'data:image/png;base64,aGk=', 'x': 1, 'y': 1, 'w': 5, 'h': 5}
        data = self.sync(self.student, [
            {'op': 'add', 'object': stroke('ok')},
            {'op': 'add', 'object': text('no-text')},
            {'op': 'add', 'object': image},
            {'op': 'add', 'object': stroke('eraser', erase=True)},
        ]).json()
        self.assertEqual(set(self.objects()), {'ok'})
        self.assertEqual([r['id'] for r in data['rejected']], ['no-text', 'img', 'eraser'])

    def test_students_only_change_their_own_elements_unless_deletion_allowed(self):
        self.configure(students_can_edit=True)
        self.sync(self.teacher, [{'op': 'add', 'object': stroke('teacher')}])
        self.sync(self.student, [{'op': 'add', 'object': stroke('mine')}])
        moved = dict(stroke('teacher'), color='#f00')
        data = self.sync(self.student, [{'op': 'update', 'object': moved}, {'op': 'delete', 'id': 'teacher'},
                                        {'op': 'clear'}, {'op': 'delete', 'id': 'mine'}]).json()
        self.assertEqual(len(data['rejected']), 3)
        self.assertEqual(data['rejected'][0]['object']['color'], '#000', 'le client reçoit la version du serveur')
        self.assertEqual(set(self.objects()), {'teacher'})
        self.configure(allow_delete=True)
        self.sync(self.student, [{'op': 'delete', 'id': 'teacher'}])
        self.assertEqual(self.objects(), {})

    def test_lock_control_and_individual_grant(self):
        grant = self.post(self.teacher, 'grant', {'user_id': self.student.pk, 'allowed': True})
        self.assertEqual(grant.status_code, 200)
        self.sync(self.student, [{'op': 'add', 'object': stroke('granted')}])
        self.sync(self.classmate, [{'op': 'add', 'object': stroke('not-granted')}])
        self.assertEqual(set(self.objects()), {'granted'})

        self.post(self.teacher, 'control', {'user_id': self.classmate.pk})
        self.sync(self.classmate, [{'op': 'delete', 'id': 'granted'}, {'op': 'background', 'background': 'dots'}])
        self.assertEqual(self.objects(), {})
        self.assertEqual(self.board.content['background'], 'dots')
        self.assertTrue(Notification.objects.filter(recipient=self.classmate, title='C’est à vous !').exists())

        self.post(self.teacher, 'settings', {'is_locked': True})
        self.sync(self.classmate, [{'op': 'add', 'object': stroke('locked')}])
        self.sync(self.student, [{'op': 'add', 'object': stroke('locked2')}])
        self.assertEqual(self.objects(), {}, 'le verrou bloque aussi l’élève qui a la main')
        self.sync(self.teacher, [{'op': 'add', 'object': stroke('teacher-still')}])
        self.assertEqual(set(self.objects()), {'teacher-still'})

        self.post(self.teacher, 'control', {'user_id': None})
        self.board.refresh_from_db()
        self.assertIsNone(self.board.controller_id)

    def test_only_the_teacher_manages_the_board(self):
        for name, payload in (('settings', {'is_locked': True}), ('control', {'user_id': self.student.pk}),
                              ('grant', {'user_id': self.student.pk, 'allowed': True}), ('zones', {'zones': []}),
                              ('share_live', {'mode': 'class'})):
            self.assertEqual(self.post(self.student, name, payload).status_code, 403, name)
        self.assertEqual(self.sync(self.outsider).status_code, 403)

    def test_workspaces_keep_each_group_in_its_column(self):
        self.configure(students_can_edit=True)
        response = self.post(self.teacher, 'zones', {'zones': [
            {'label': 'Groupe A', 'members': [self.student.pk]},
            {'label': 'Groupe B', 'members': [self.classmate.pk]},
        ]})
        self.assertEqual(response.status_code, 200)
        self.sync(self.student, [{'op': 'add', 'object': stroke('a-left', x=100)},
                                 {'op': 'add', 'object': stroke('a-right', x=1200)}])
        self.sync(self.classmate, [{'op': 'add', 'object': stroke('b-right', x=1200)}])
        self.assertEqual(set(self.objects()), {'a-left', 'b-right'})
        self.assertEqual(self.sync(self.student).json()['state']['caps']['zone'], 0)

    def test_raised_hand_notifies_the_teacher_and_is_cleared_by_a_grant(self):
        self.post(self.student, 'hand', {'raised': True})
        state = self.sync(self.teacher).json()['state']
        omar = next(p for p in state['participants'] if p['id'] == self.student.pk)
        self.assertTrue(omar['hand'])
        self.assertTrue(Notification.objects.filter(recipient=self.teacher, title='Demande de participation').exists())
        self.post(self.teacher, 'grant', {'user_id': self.student.pk, 'allowed': True})
        state = self.sync(self.teacher).json()['state']
        omar = next(p for p in state['participants'] if p['id'] == self.student.pk)
        self.assertFalse(omar['hand'])
        self.assertTrue(omar['granted'])

    def test_presence_and_cursor_are_shared(self):
        self.sync(self.student, cursor={'x': 321, 'y': 77})
        state = self.sync(self.teacher).json()['state']
        omar = next(p for p in state['participants'] if p['id'] == self.student.pk)
        self.assertTrue(omar['online'])
        self.assertEqual(omar['cursor'], {'x': 321.0, 'y': 77.0})

    # --- Partage ---------------------------------------------------------
    def test_selected_students_only(self):
        response = self.post(self.teacher, 'share_live', {'mode': 'selected', 'student_ids': [self.student.pk]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.sync(self.student).status_code, 200)
        self.assertEqual(self.sync(self.classmate).status_code, 403)
        self.login(self.student)
        self.assertContains(self.client.get(reverse('whiteboard:list')), 'Équations')
        self.login(self.classmate)
        self.assertNotContains(self.client.get(reverse('whiteboard:list')), 'Équations')
        self.assertTrue(Notification.objects.filter(recipient=self.student, title='Tableau partagé avec vous').exists())
        self.assertFalse(Notification.objects.filter(recipient=self.classmate, title='Tableau partagé avec vous').exists())

    def test_share_with_class_posts_link_in_class_chat(self):
        self.configure(access_mode='selected')
        self.post(self.teacher, 'share_live', {'mode': 'class', 'post_to_chat': True})
        message = ChatMessage.objects.get()
        self.assertIn(reverse('whiteboard:room', args=[self.board.pk]), message.body)
        self.assertEqual(Notification.objects.filter(title='Tableau partagé avec vous').count(), 2)

    def test_share_from_a_consultation_creates_board_and_posts_link(self):
        conversation = PrivateConversation.objects.create(
            classroom=self.classroom, student=self.student, teacher=self.teacher)
        self.login(self.teacher)
        response = self.client.post(reverse('whiteboard:share_to_conversation'), json.dumps({
            'kind': 'consultation', 'conversation_id': conversation.pk, 'title': 'Aide exercice 3',
        }), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        board = WhiteboardBoard.objects.get(title='Aide exercice 3')
        self.assertEqual(board.access_mode, 'selected')
        self.assertEqual(list(board.participants.all()), [self.student])
        self.assertIn(f'/tableau/{board.pk}/', PrivateMessage.objects.get().body)
        self.login(self.classmate)
        self.assertEqual(self.client.get(reverse('whiteboard:room', args=[board.pk])).status_code, 403)
        self.login(self.student)
        self.assertEqual(self.client.get(reverse('whiteboard:room', args=[board.pk])).status_code, 200)
        self.login(self.student)
        refused = self.client.post(reverse('whiteboard:share_to_conversation'), json.dumps({
            'kind': 'consultation', 'conversation_id': conversation.pk, 'title': 'x'}), content_type='application/json')
        self.assertEqual(refused.status_code, 403)

    def test_op_log_is_bounded_and_ops_are_numbered(self):
        self.sync(self.teacher, [{'op': 'add', 'object': stroke(f'o{i}')} for i in range(3)])
        self.assertEqual(list(WhiteboardOp.objects.values_list('revision', flat=True)), [1, 2, 3])
        self.board.refresh_from_db()
        self.assertEqual(self.board.revision, 3)

    def test_student_room_shows_participation_controls(self):
        self.login(self.student)
        page = self.client.get(reverse('whiteboard:room', args=[self.board.pk]))
        self.assertContains(page, 'id="wbHandBtn"')
        self.assertContains(page, 'whiteboard-collab.js')
        self.assertNotContains(page, 'id="wbPermForm"')
        self.login(self.teacher)
        page = self.client.get(reverse('whiteboard:room', args=[self.board.pk]))
        self.assertContains(page, 'id="wbPermForm"')
        self.assertContains(page, 'id="wbLiveShare"')
