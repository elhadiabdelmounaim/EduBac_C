"""Le chat de classe ne doit jamais stocker ni servir en ligne un fichier exécutable."""
import tempfile

from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from classrooms.models import Classroom
from .models import ChatMessage, ClassChatRoom


@override_settings(ALLOWED_HOSTS=['testserver'])
class ClassChatUploadSecurityTests(TestCase):
    def setUp(self):
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        override = override_settings(MEDIA_ROOT=media.name)
        override.enable()
        self.addCleanup(override.disable)
        self.teacher = User.objects.create_user(username='t', email='t@example.test', role='teacher')
        self.student = User.objects.create_user(username='s', email='s@example.test', role='student')
        self.classroom = Classroom.objects.create(name='Maths', teacher=self.teacher, niveau='tronc_commun')
        self.classroom.add_member(self.student)
        session = self.client.session
        session['user_id'] = self.student.pk
        session.save()
        self.send_url = reverse('chat:api_send', args=[self.classroom.pk])

    def test_voice_flag_does_not_bypass_extension_check(self):
        for name in ('evil.html', 'evil.svg', 'evil'):
            response = self.client.post(self.send_url, {
                'attachment': SimpleUploadedFile(name, b'<script>alert(1)</script>', content_type='text/html'),
                'is_voice': '1',
            })
            self.assertEqual(response.status_code, 400, name)
        self.assertFalse(ChatMessage.objects.exists())

    def test_voice_flag_requires_audio_file(self):
        response = self.client.post(self.send_url, {
            'attachment': SimpleUploadedFile('notes.pdf', b'%PDF-1.4', content_type='application/pdf'),
            'is_voice': '1',
        })
        self.assertEqual(response.status_code, 400)

    def test_documents_are_downloaded_not_rendered(self):
        response = self.client.post(self.send_url, {
            'attachment': SimpleUploadedFile('cours.pdf', b'%PDF-1.4', content_type='application/pdf'),
        })
        self.assertEqual(response.status_code, 200)
        message = ChatMessage.objects.get()
        download = self.client.get(reverse('chat:attachment', args=[message.pk]))
        self.assertTrue(download['Content-Disposition'].startswith('attachment'))

    def test_legacy_html_attachment_is_never_served_inline(self):
        room = ClassChatRoom.get_or_create_for(self.classroom)
        message = ChatMessage(room=room, sender=self.student, is_voice=True)
        message.attachment.save('legacy.html', ContentFile(b'<script>alert(1)</script>'), save=True)
        response = self.client.get(reverse('chat:attachment', args=[message.pk]))
        self.assertTrue(response['Content-Disposition'].startswith('attachment'))
