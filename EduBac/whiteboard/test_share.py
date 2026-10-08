import io
import tempfile
from unittest.mock import AsyncMock, Mock

from PIL import Image
from asgiref.sync import async_to_sync
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from classrooms.models import Classroom
from notifications.models import Notification
from whiteboard.consumers import WhiteboardShareConsumer
from whiteboard.models import WhiteboardBoard, WhiteboardShare


def _png(width=8, height=8):
    buf = io.BytesIO()
    Image.new('RGB', (width, height), 'white').save(buf, 'PNG')
    return buf.getvalue()


def _jpeg():
    buf = io.BytesIO()
    Image.new('RGB', (8, 8), 'red').save(buf, 'JPEG')
    return buf.getvalue()


@override_settings(ALLOWED_HOSTS=['testserver'], MEDIA_ROOT=tempfile.mkdtemp())
class WhiteboardShareTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(
            username='teacher', email='teacher@test.local', role='teacher',
        )
        self.other_teacher = User.objects.create_user(
            username='other-teacher', email='other-teacher@test.local', role='teacher',
        )
        self.student = User.objects.create_user(
            username='student', email='student@test.local', role='student',
        )
        self.other_student = User.objects.create_user(
            username='other-student', email='other-student@test.local', role='student',
        )
        self.classroom = Classroom.objects.create(
            name='Mathématiques', teacher=self.teacher, niveau='1ere_bac_sc',
        )
        self.other_class = Classroom.objects.create(
            name='Autre classe', teacher=self.other_teacher, niveau='1ere_bac_sc',
        )
        self.classroom.add_member(self.student)
        self.other_class.add_member(self.other_student)
        self.board = WhiteboardBoard.objects.create(
            title='Fonctions', created_by=self.teacher, classroom=self.classroom,
            content={'objects': [], 'version': 1},
        )
        self.url = reverse('whiteboard:share_create')

    def login(self, user):
        session = self.client.session
        session['user_id'] = user.pk
        session.save()

    def post_share(self, classroom, title='Fonctions', payload=None, content_type='image/png'):
        upload = payload if payload is not None else _png()
        image = SimpleUploadedFile('board.png', upload, content_type=content_type)
        return self.client.post(self.url, {
            'classroom_id': classroom.pk,
            'title': title,
            'image': image,
        })

    def test_teacher_shares_png_with_one_class_only(self):
        self.login(self.teacher)
        response = self.post_share(self.classroom, title='Mathématiques — Fonctions')
        self.assertEqual(response.status_code, 200)
        share = WhiteboardShare.objects.get()
        self.assertEqual(share.teacher, self.teacher)
        self.assertEqual(share.classroom, self.classroom)
        self.assertEqual(share.title, 'Mathématiques — Fonctions')
        self.assertTrue(share.image.name.endswith('.png'))
        self.assertNotIn('/media/', response.json()['share']['image_url'])
        self.assertIn("Aujourd", share.when_label())
        self.assertTrue(
            Notification.objects.filter(recipient=self.student, type='classroom').exists()
        )
        self.assertFalse(
            Notification.objects.filter(recipient=self.other_student).exists()
        )

    def test_teacher_cannot_share_with_another_class_or_a_non_png(self):
        self.login(self.teacher)
        denied = self.post_share(self.other_class)
        self.assertEqual(denied.status_code, 403)
        rejected = self.post_share(self.classroom, payload=_jpeg(), content_type='image/jpeg')
        self.assertEqual(rejected.status_code, 400)
        self.login(self.student)
        forbidden = self.post_share(self.classroom)
        self.assertEqual(forbidden.status_code, 403)
        self.assertEqual(WhiteboardShare.objects.count(), 0)

    def test_student_sees_only_the_share_of_their_class(self):
        self.login(self.teacher)
        self.post_share(self.classroom, title='Dérivées')
        share = WhiteboardShare.objects.get()

        self.login(self.student)
        page = self.client.get(reverse('whiteboard:share_view', args=[share.pk]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'Lecture seule')
        self.assertContains(page, 'Dérivées')
        self.assertNotContains(page, 'id="wbShare"')
        self.assertNotContains(page, 'data-tool="pencil"')
        self.assertNotContains(page, '/media/whiteboards')
        image = self.client.get(reverse('whiteboard:share_image', args=[share.pk]))
        self.assertEqual(image.status_code, 200)
        self.assertEqual(image['Content-Type'], 'image/png')
        self.assertTrue(b''.join(image.streaming_content).startswith(b'\x89PNG'))
        feed = self.client.get(reverse('whiteboard:share_api'))
        self.assertEqual(feed.status_code, 200)
        self.assertEqual([item['id'] for item in feed.json()['shares']], [share.pk])
        board = self.client.get(reverse('whiteboard:list'))
        self.assertContains(board, 'Lecture seule')
        self.assertContains(board, 'Dérivées')
        home = self.client.get(reverse('accounts:dashboard'))
        self.assertContains(home, 'Lecture seule')

        self.login(self.other_student)
        self.assertEqual(
            self.client.get(reverse('whiteboard:share_view', args=[share.pk])).status_code,
            403,
        )
        denied_image = self.client.get(reverse('whiteboard:share_image', args=[share.pk]))
        self.assertEqual(denied_image.status_code, 403)
        self.assertNotIn(b'\x89PNG', denied_image.content)
        other_feed = self.client.get(
            reverse('whiteboard:share_api') + f'?classroom={self.classroom.pk}'
        )
        self.assertEqual(other_feed.status_code, 403)
        own_feed = self.client.get(reverse('whiteboard:share_api'))
        self.assertEqual(own_feed.json()['shares'], [])
        empty = self.client.get(reverse('whiteboard:list'))
        self.assertNotContains(empty, 'Dérivées')
        self.assertContains(empty, 'id="wbShareWatch"')
        self.assertContains(empty, 'Aucun whiteboard')

    def test_teacher_room_offers_share_and_student_room_does_not(self):
        self.login(self.teacher)
        room = self.client.get(reverse('whiteboard:room', args=[self.board.pk]))
        self.assertContains(room, 'id="wbShare"')
        self.assertContains(room, self.classroom.name)
        self.login(self.student)
        student_room = self.client.get(reverse('whiteboard:room', args=[self.board.pk]))
        self.assertEqual(student_room.status_code, 200)
        self.assertNotContains(student_room, 'id="wbShare"')

    def test_share_socket_rejects_another_class_and_ignores_client_messages(self):
        consumer = WhiteboardShareConsumer()
        self.assertTrue(async_to_sync(consumer._can_access)(self.student, self.classroom.pk))
        self.assertFalse(async_to_sync(consumer._can_access)(self.other_student, self.classroom.pk))
        self.assertFalse(async_to_sync(consumer._can_access)(self.other_teacher, self.classroom.pk))
        consumer.channel_layer = Mock(group_send=AsyncMock())
        consumer.send = AsyncMock()
        async_to_sync(consumer.receive)(text_data='{"type":"share","title":"pirate"}')
        consumer.channel_layer.group_send.assert_not_called()
        consumer.send.assert_not_called()
