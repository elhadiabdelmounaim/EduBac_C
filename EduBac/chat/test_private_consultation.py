import json
import tempfile
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from classrooms.models import Classroom, ClassroomMember
from .models import PrivateConversation, PrivateMessage
from .storage import PrivateChatStorage


@override_settings(ALLOWED_HOSTS=['testserver'])
class PrivateConsultationTests(TestCase):
    def setUp(self):
        self.private_files = tempfile.TemporaryDirectory()
        self.addCleanup(self.private_files.cleanup)
        attachment_field = PrivateMessage._meta.get_field('attachment')
        self.original_storage = attachment_field.storage
        attachment_field.storage = PrivateChatStorage(location=self.private_files.name)
        self.addCleanup(setattr, attachment_field, 'storage', self.original_storage)
        self.teacher = User.objects.create_user(
            username='private_teacher',
            email='private-teacher@example.test',
            role='teacher',
        )
        self.student = User.objects.create_user(
            username='private_student',
            email='private-student@example.test',
            first_name='Élève',
            last_name='Test',
            role='student',
        )
        self.outsider = User.objects.create_user(
            username='private_outsider',
            email='private-outsider@example.test',
            role='student',
        )
        self.classroom = Classroom.objects.create(
            name='Classe privée',
            niveau='1ere_bac_sm',
            teacher=self.teacher,
            is_active=False,
        )
        self.membership = ClassroomMember.objects.create(
            classroom=self.classroom,
            user=self.student,
        )

    def login_as(self, user):
        session = self.client.session
        session['user_id'] = user.pk
        session.save()

    def test_student_class_page_shows_only_requested_details_and_button(self):
        classmate = User.objects.create_user(
            username='classmate_private',
            email='classmate-private@example.test',
            role='student',
        )
        ClassroomMember.objects.create(classroom=self.classroom, user=classmate)
        self.login_as(self.student)

        response = self.client.get(reverse(
            'classrooms:detail',
            args=[self.classroom.pk],
        ))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Ma classe')
        self.assertContains(response, self.classroom.get_niveau_display())
        self.assertContains(response, self.membership.joined_at.strftime('%d/%m/%Y'))
        self.assertContains(response, 'Inactive')
        self.assertContains(response, self.classroom.code)
        self.assertContains(response, 'Consulter le professeur')
        self.assertContains(
            response,
            reverse('chat:private_student_chat', args=[self.classroom.pk]),
        )
        self.assertNotContains(response, 'Élèves (')
        self.assertNotContains(response, self.teacher.email)
        self.assertNotContains(response, classmate.username)
        self.assertNotContains(response, classmate.email)

    def test_student_can_start_private_chat_and_teacher_can_reply(self):
        self.login_as(self.student)
        start = self.client.get(reverse(
            'chat:private_student_chat',
            args=[self.classroom.pk],
        ))
        self.assertEqual(start.status_code, 302)
        conversation = PrivateConversation.objects.get(
            classroom=self.classroom,
            student=self.student,
            teacher=self.teacher,
        )
        room_url = reverse('chat:private_room', args=[conversation.pk])
        self.assertRedirects(start, room_url)
        self.assertEqual(self.client.get(room_url).status_code, 200)

        send_student = self.client.post(
            reverse('chat:api_private_send', args=[conversation.pk]),
            data=json.dumps({'body': 'Bonjour, professeur.'}),
            content_type='application/json',
        )
        self.assertEqual(send_student.status_code, 200)
        self.assertEqual(PrivateMessage.objects.count(), 1)

        self.login_as(self.teacher)
        inbox = self.client.get(reverse('chat:private_inbox'))
        self.assertContains(inbox, self.student.get_full_name())
        self.assertContains(inbox, self.classroom.get_niveau_display())
        received = self.client.get(
            reverse('chat:api_private_messages', args=[conversation.pk]),
        )
        self.assertEqual(received.status_code, 200)
        self.assertEqual(received.json()['messages'][0]['body'], 'Bonjour, professeur.')
        self.assertEqual(received.json()['messages'][0]['sender_id'], self.student.pk)
        self.assertTrue(received.json()['messages'][0]['is_read'])

        send_teacher = self.client.post(
            reverse('chat:api_private_send', args=[conversation.pk]),
            data=json.dumps({'body': 'Bonjour, comment puis-je vous aider ?'}),
            content_type='application/json',
        )
        self.assertEqual(send_teacher.status_code, 200)

        self.login_as(self.student)
        latest = self.client.get(
            reverse('chat:api_private_messages', args=[conversation.pk]),
            {'after_id': send_student.json()['message']['id']},
        )
        self.assertEqual(latest.status_code, 200)
        self.assertEqual(
            latest.json()['messages'][0]['body'],
            'Bonjour, comment puis-je vous aider ?',
        )
        self.assertIn(send_student.json()['message']['id'], latest.json()['read_ids'])

    def test_private_chat_page_exposes_media_recording_and_emoji_controls(self):
        self.login_as(self.student)
        conversation = self._conversation()

        response = self.client.get(reverse('chat:private_room', args=[conversation.pk]))

        self.assertEqual(response.status_code, 200)
        for control in (
            'privateFileBtn',
            'privateImageBtn',
            'privateAudioBtn',
            'chatVoiceBtn',
            'privateEmojiBtn',
            'chatVoiceStop',
            'chatVoiceSend',
        ):
            self.assertContains(response, f'id="{control}"')
        page = response.content.decode()
        self.assertLess(page.index('chat-voice.js'), page.index('private-chat.js'))

    def test_private_image_and_audio_uploads_are_delivered_only_to_participants(self):
        self.login_as(self.student)
        image_response = self.client.post(
            reverse('chat:api_private_send', args=[
                self._conversation().pk,
            ]),
            {
                'body': 'Regardez cette image.',
                'attachment': SimpleUploadedFile(
                    'exercice.png', b'private-image-data', content_type='image/png',
                ),
            },
        )
        self.assertEqual(image_response.status_code, 200)
        image_message = image_response.json()['message']
        self.assertTrue(image_message['is_image'])
        self.assertTrue(image_message['attachment_url'].startswith('/chat/consultations/attachments/'))
        self.assertNotIn('/media/', image_message['attachment_url'])
        private_root = Path(PrivateMessage._meta.get_field('attachment').storage.location).resolve()
        media_root = Path(settings.MEDIA_ROOT).resolve()
        self.assertFalse(private_root == media_root or media_root in private_root.parents)
        image_download = self.client.get(image_message['attachment_url'])
        self.assertEqual(image_download.status_code, 200)
        self.assertEqual(image_download['Cache-Control'], 'private, no-store')
        self.assertIn('inline', image_download['Content-Disposition'])

        audio_response = self.client.post(
            reverse('chat:api_private_send', args=[self._conversation().pk]),
            {
                'attachment': SimpleUploadedFile(
                    'explication.mp3', b'private-audio-data', content_type='audio/mpeg',
                ),
            },
        )
        self.assertEqual(audio_response.status_code, 200)
        audio_message = audio_response.json()['message']
        self.assertTrue(audio_message['is_voice'])
        self.login_as(self.teacher)
        audio_download = self.client.get(audio_message['attachment_url'])
        self.assertEqual(audio_download.status_code, 200)
        self.assertTrue(audio_download['Content-Type'].startswith('audio/'))
        self.assertIn('inline', audio_download['Content-Disposition'])
        self.login_as(self.outsider)
        self.assertEqual(self.client.get(image_message['attachment_url']).status_code, 404)
        self.assertEqual(self.client.get(audio_message['attachment_url']).status_code, 404)

    def _conversation(self):
        conversation, _ = PrivateConversation.objects.get_or_create(
            classroom=self.classroom,
            student=self.student,
            teacher=self.teacher,
        )
        return conversation

    def test_private_conversation_is_hidden_from_nonparticipants(self):
        conversation = PrivateConversation.objects.create(
            classroom=self.classroom,
            student=self.student,
            teacher=self.teacher,
        )
        self.login_as(self.outsider)

        self.assertEqual(
            self.client.get(reverse('chat:private_room', args=[conversation.pk])).status_code,
            404,
        )
        api_response = self.client.get(
            reverse('chat:api_private_messages', args=[conversation.pk]),
            HTTP_ACCEPT='application/json',
        )
        self.assertEqual(api_response.status_code, 404)
        self.assertEqual(api_response['Content-Type'], 'application/json')
        self.assertEqual(self.client.get(reverse('chat:private_inbox')).status_code, 403)

    def test_unauthenticated_private_api_returns_json_instead_of_login_html(self):
        conversation = self._conversation()

        response = self.client.get(
            reverse('chat:api_private_messages', args=[conversation.pk]),
            HTTP_ACCEPT='application/json',
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response['Content-Type'], 'application/json')
        self.assertIn('session', response.json()['error'].lower())

    def test_removed_student_cannot_continue_private_conversation(self):
        conversation = PrivateConversation.objects.create(
            classroom=self.classroom,
            student=self.student,
            teacher=self.teacher,
        )
        self.membership.delete()
        self.login_as(self.student)

        self.assertEqual(
            self.client.get(reverse('chat:private_room', args=[conversation.pk])).status_code,
            404,
        )
