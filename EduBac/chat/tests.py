import io
import tempfile
import wave

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from accounts.models import User
from classrooms.models import Classroom
from .models import ChatMessage


@override_settings(ALLOWED_HOSTS=['testserver'])
class VoiceMessageTests(TestCase):
    def setUp(self):
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        self.settings_override = override_settings(MEDIA_ROOT=media.name)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.teacher = User.objects.create_user(username='teacher', email='teacher@example.test', role='teacher')
        self.student = User.objects.create_user(username='student', email='student@example.test', role='student')
        self.room = Classroom.objects.create(name='Maths', teacher=self.teacher, niveau='tronc_commun')
        self.room.add_member(self.student)
        self.login_as(self.student)

    def login_as(self, user):
        session = self.client.session
        session['user_id'] = user.pk
        session.save()

    def audio_file(self):
        data = io.BytesIO()
        with wave.open(data, 'wb') as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(8000)
            audio.writeframes(b'\x00\x00' * 800)
        return SimpleUploadedFile('message.wav', data.getvalue(), content_type='audio/wav')

    def test_voice_is_saved_and_returned_after_reloading_conversation(self):
        sent = self.client.post(f'/chat/api/classe/{self.room.pk}/send/', {
            'attachment': self.audio_file(), 'is_voice': '1',
        })
        self.assertEqual(sent.status_code, 200)
        message = sent.json()['message']
        self.assertTrue(message['is_voice'])
        self.assertTrue(message['attachment_url'].endswith('.wav'))
        self.login_as(self.teacher)
        received = self.client.get(f'/chat/api/classe/{self.room.pk}/messages/').json()['messages']
        self.assertEqual(received[0]['id'], message['id'])
        self.assertTrue(received[0]['is_voice'])
        self.assertEqual(received[0]['attachment_url'], message['attachment_url'])

    def test_uploaded_audio_is_recognized_without_recording_flag(self):
        response = self.client.post(f'/chat/api/classe/{self.room.pk}/send/', {
            'attachment': self.audio_file(),
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['message']['is_voice'])

    def test_room_loads_player_before_message_renderer_and_keeps_microphone(self):
        response = self.client.get(f'/chat/classe/{self.room.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '/static/css/chat-voice.css')
        self.assertContains(response, 'id="chatVoiceBtn"')
        html = response.content.decode()
        self.assertLess(html.index('/static/js/chat-voice.js'), html.index('/static/js/chat.js'))

    def test_nonmember_cannot_send_or_list_voice_messages(self):
        outsider = User.objects.create_user(username='outsider', email='outsider@example.test')
        self.login_as(outsider)
        response = self.client.post(f'/chat/api/classe/{self.room.pk}/send/', {
            'attachment': self.audio_file(), 'is_voice': '1',
        })
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.get(f'/chat/api/classe/{self.room.pk}/messages/').status_code, 403)
        self.assertFalse(ChatMessage.objects.exists())
