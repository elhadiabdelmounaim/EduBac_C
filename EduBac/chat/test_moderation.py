"""Modération, contexte pédagogique, synchronisation et outils de la messagerie."""
import io
import json
import tempfile
from datetime import time, timedelta
from pathlib import Path
from unittest.mock import patch

from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from classrooms.models import Classroom, ClassroomMember
from education.models import Course, Lesson
from quizzes.models import Attempt, Question, Quiz

from .models import (
    ChatBlock,
    ChatMessage,
    ChatMute,
    ChatReport,
    ClassChatRoom,
    DirectConversation,
    DirectMessage,
    PrivateConversation,
    PrivateMessage,
)

PNG = b'\x89PNG\r\n\x1a\n' + b'0' * 32


@override_settings(ALLOWED_HOSTS=['testserver'], EMAIL_NOTIFICATIONS_ENABLED=False)
class ChatTestBase(TestCase):
    def setUp(self):
        media = tempfile.TemporaryDirectory()
        private = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        self.addCleanup(private.cleanup)
        self.media_root = media.name
        override = override_settings(MEDIA_ROOT=media.name)
        override.enable()
        self.addCleanup(override.disable)
        for model in (ChatMessage, PrivateMessage, DirectMessage):
            storage = model._meta.get_field('attachment').storage
            patcher = patch.object(storage, 'location', private.name)
            patcher.start()
            self.addCleanup(patcher.stop)
            for attr in ('base_location',):
                if attr in storage.__dict__:
                    del storage.__dict__[attr]
        self.teacher = User.objects.create_user(username='prof', email='prof@example.test', role='teacher')
        self.other_teacher = User.objects.create_user(username='prof2', email='prof2@example.test', role='teacher')
        self.student = User.objects.create_user(username='amal', email='a@example.test', role='student', first_name='Amal')
        self.classmate = User.objects.create_user(username='badr', email='b@example.test', role='student', first_name='Badr')
        self.admin = User.objects.create_superuser(username='root', email='root@example.test', password='x')
        self.classroom = Classroom.objects.create(name='TC1', niveau='tronc_commun', teacher=self.teacher)
        ClassroomMember.objects.create(classroom=self.classroom, user=self.student)
        ClassroomMember.objects.create(classroom=self.classroom, user=self.classmate)
        self.room = ClassChatRoom.get_or_create_for(self.classroom)

    def login_as(self, user):
        session = self.client.session
        session['user_id'] = user.pk
        session.save()

    def post_json(self, url, data=None):
        return self.client.post(
            url, data=json.dumps(data or {}), content_type='application/json',
            HTTP_ACCEPT='application/json',
        )

    def send_class(self, body='Bonjour'):
        return self.post_json(reverse('chat:api_send', args=[self.classroom.pk]), {'body': body})


class StudentDirectMessagesTests(ChatTestBase):
    def start(self, target):
        return self.post_json(reverse('chat:api_direct_start'), {'user_id': target.pk})

    def test_peer_messages_are_disabled_until_teacher_enables_them(self):
        self.login_as(self.student)
        self.assertEqual(self.start(self.classmate).status_code, 403)
        contacts = self.client.get(reverse('chat:api_direct_contacts')).json()['contacts']
        self.assertNotIn(self.classmate.pk, {c['id'] for c in contacts})

        self.login_as(self.teacher)
        response = self.post_json(
            reverse('chat:api_room_settings', args=[self.classroom.pk]),
            {'allow_student_direct': True},
        )
        self.assertTrue(response.json()['room']['allow_student_direct'])

        self.login_as(self.student)
        self.assertEqual(self.start(self.classmate).status_code, 200)

    def test_disabling_peer_messages_hides_existing_conversation(self):
        self.room.allow_student_direct = True
        self.room.save()
        conversation, _ = DirectConversation.get_or_create_for(self.student, self.classmate, self.classroom)
        self.room.allow_student_direct = False
        self.room.save()
        self.login_as(self.student)
        response = self.client.get(reverse('chat:api_direct_messages', args=[conversation.pk]))
        self.assertEqual(response.status_code, 404)

    def test_block_prevents_sending_and_new_conversations(self):
        self.room.allow_student_direct = True
        self.room.save()
        conversation, _ = DirectConversation.get_or_create_for(self.student, self.classmate, self.classroom)
        self.login_as(self.classmate)
        self.assertTrue(self.post_json(reverse('chat:api_block'), {'user_id': self.student.pk}).json()['blocked'])

        self.login_as(self.student)
        send = self.post_json(reverse('chat:api_direct_send', args=[conversation.pk]), {'body': 'Salut'})
        self.assertEqual(send.status_code, 403)
        self.assertEqual(self.start(self.classmate).status_code, 403)
        # L'historique reste lisible.
        self.assertEqual(
            self.client.get(reverse('chat:api_direct_messages', args=[conversation.pk])).status_code, 200,
        )

        self.login_as(self.classmate)
        self.post_json(reverse('chat:api_block'), {'user_id': self.student.pk, 'blocked': False})
        self.login_as(self.student)
        send = self.post_json(reverse('chat:api_direct_send', args=[conversation.pk]), {'body': 'Salut'})
        self.assertEqual(send.status_code, 200)

    def test_teacher_cannot_block(self):
        self.login_as(self.teacher)
        response = self.post_json(reverse('chat:api_block'), {'user_id': self.student.pk})
        self.assertEqual(response.status_code, 403)


class EditDeleteTests(ChatTestBase):
    def test_author_can_edit_within_window_only(self):
        self.login_as(self.student)
        message = self.send_class('Bonjour').json()['message']
        url = reverse('chat:api_message_edit', args=['class', message['id']])
        response = self.post_json(url, {'body': 'Bonsoir'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['message']['is_edited'])
        self.assertEqual(ChatMessage.objects.get().body, 'Bonsoir')

        ChatMessage.objects.update(created_at=timezone.now() - timedelta(minutes=10))
        self.assertEqual(self.post_json(url, {'body': 'Trop tard'}).status_code, 403)

    def test_only_author_can_edit(self):
        self.login_as(self.student)
        message = self.send_class().json()['message']
        self.login_as(self.teacher)
        url = reverse('chat:api_message_edit', args=['class', message['id']])
        self.assertEqual(self.post_json(url, {'body': 'x'}).status_code, 403)

    def test_teacher_deletes_student_message_and_content_is_hidden(self):
        self.login_as(self.student)
        message = self.send_class('Insulte').json()['message']
        self.login_as(self.classmate)
        url = reverse('chat:api_message_delete', args=['class', message['id']])
        self.assertEqual(self.post_json(url).status_code, 403)

        self.login_as(self.teacher)
        payload = self.post_json(url).json()['message']
        self.assertTrue(payload['is_deleted'])
        self.assertTrue(payload['deleted_by_moderator'])
        self.assertEqual(payload['body'], '')

        self.login_as(self.classmate)
        listed = self.client.get(reverse('chat:api_messages', args=[self.classroom.pk])).json()['messages']
        self.assertEqual(listed[0]['body'], '')
        self.assertNotIn('Insulte', json.dumps(listed))

    def test_deleted_attachment_is_no_longer_served(self):
        self.login_as(self.student)
        response = self.client.post(reverse('chat:api_send', args=[self.classroom.pk]), {
            'attachment': SimpleUploadedFile('image.png', PNG, content_type='image/png'),
        })
        message = response.json()['message']
        self.assertEqual(self.client.get(message['attachment_url']).status_code, 200)
        self.post_json(reverse('chat:api_message_delete', args=['class', message['id']]))
        self.assertEqual(self.client.get(message['attachment_url']).status_code, 404)

    def test_private_message_edit_and_delete(self):
        conversation = PrivateConversation.objects.create(
            classroom=self.classroom, student=self.student, teacher=self.teacher,
        )
        self.login_as(self.student)
        sent = self.post_json(
            reverse('chat:api_private_send', args=[conversation.pk]), {'body': 'Question'},
        ).json()['message']
        self.post_json(reverse('chat:api_message_edit', args=['consultation', sent['id']]), {'body': 'Question ?'})
        self.assertEqual(PrivateMessage.objects.get().body, 'Question ?')
        self.login_as(self.teacher)
        self.assertEqual(
            self.post_json(reverse('chat:api_message_delete', args=['consultation', sent['id']])).status_code,
            403,
        )

    def test_changes_are_synchronised_with_since(self):
        self.login_as(self.student)
        message = self.send_class('Avant').json()['message']
        first = self.client.get(reverse('chat:api_messages', args=[self.classroom.pk])).json()
        self.post_json(reverse('chat:api_message_edit', args=['class', message['id']]), {'body': 'Après'})
        sync = self.client.get(reverse('chat:api_messages', args=[self.classroom.pk]), {
            'after_id': message['id'], 'since': first['server_time'],
        }).json()
        self.assertEqual([m['body'] for m in sync['messages']], ['Après'])


class RoomRestrictionTests(ChatTestBase):
    def test_locked_room_only_accepts_teacher(self):
        self.room.is_locked = True
        self.room.save()
        self.login_as(self.student)
        response = self.send_class()
        self.assertEqual(response.status_code, 403)
        state = self.client.get(reverse('chat:api_messages', args=[self.classroom.pk])).json()['room']
        self.assertFalse(state['can_post'])
        self.login_as(self.teacher)
        self.assertEqual(self.send_class().status_code, 200)

    def test_mute_and_unmute(self):
        self.login_as(self.teacher)
        url = reverse('chat:api_room_mute', args=[self.classroom.pk])
        self.assertEqual(self.post_json(url, {'user_id': self.student.pk, 'minutes': 60}).status_code, 200)
        self.login_as(self.student)
        self.assertEqual(self.send_class().status_code, 403)
        self.login_as(self.teacher)
        members = self.client.get(reverse('chat:api_room_members', args=[self.classroom.pk])).json()
        muted = next(m for m in members['members'] if m['id'] == self.student.pk)
        self.assertTrue(muted['muted_until'])
        self.post_json(url, {'user_id': self.student.pk, 'minutes': 0})
        self.login_as(self.student)
        self.assertEqual(self.send_class().status_code, 200)

    def test_mute_rejects_outsiders_and_students(self):
        outsider = User.objects.create_user(username='zz', email='zz@example.test', role='student')
        self.login_as(self.teacher)
        url = reverse('chat:api_room_mute', args=[self.classroom.pk])
        self.assertEqual(self.post_json(url, {'user_id': outsider.pk, 'minutes': 60}).status_code, 404)
        self.login_as(self.student)
        self.assertEqual(self.post_json(url, {'user_id': self.classmate.pk, 'minutes': 60}).status_code, 403)
        self.login_as(self.other_teacher)
        self.assertEqual(self.post_json(url, {'user_id': self.student.pk, 'minutes': 60}).status_code, 403)

    def test_quiet_hours_apply_to_students_in_class_and_consultation(self):
        now = timezone.localtime().time()
        start = (timezone.localtime() - timedelta(minutes=5)).time().replace(second=0, microsecond=0)
        end = (timezone.localtime() + timedelta(minutes=30)).time().replace(second=0, microsecond=0)
        self.assertNotEqual(start, end, now)
        self.login_as(self.teacher)
        self.post_json(reverse('chat:api_room_settings', args=[self.classroom.pk]), {
            'quiet_hours_start': start.strftime('%H:%M'), 'quiet_hours_end': end.strftime('%H:%M'),
        })
        conversation = PrivateConversation.objects.create(
            classroom=self.classroom, student=self.student, teacher=self.teacher,
        )
        self.login_as(self.student)
        self.assertEqual(self.send_class().status_code, 403)
        self.assertEqual(
            self.post_json(reverse('chat:api_private_send', args=[conversation.pk]), {'body': 'x'}).status_code,
            403,
        )
        self.login_as(self.teacher)
        self.assertEqual(self.send_class().status_code, 200)

    def test_quiet_hours_across_midnight(self):
        self.room.quiet_hours_start = time(22, 0)
        self.room.quiet_hours_end = time(7, 0)
        late = timezone.make_aware(timezone.datetime(2026, 1, 1, 23, 30))
        early = timezone.make_aware(timezone.datetime(2026, 1, 1, 6, 0))
        noon = timezone.make_aware(timezone.datetime(2026, 1, 1, 12, 0))
        self.assertTrue(self.room.in_quiet_hours(late))
        self.assertTrue(self.room.in_quiet_hours(early))
        self.assertFalse(self.room.in_quiet_hours(noon))

    def test_invalid_settings_are_rejected(self):
        self.login_as(self.teacher)
        url = reverse('chat:api_room_settings', args=[self.classroom.pk])
        self.assertEqual(self.post_json(url, {'quiet_hours_start': '25:00', 'quiet_hours_end': '07:00'}).status_code, 400)
        self.assertEqual(self.post_json(url, {'quiet_hours_start': '22:00', 'quiet_hours_end': ''}).status_code, 400)


class ReportTests(ChatTestBase):
    def report(self, kind, message_id, reason='harassment'):
        return self.post_json(
            reverse('chat:api_message_report', args=[kind, message_id]),
            {'reason': reason, 'details': 'Pas correct'},
        )

    def test_report_creates_snapshot_and_reaches_teacher(self):
        self.login_as(self.classmate)
        self.send_class('Contexte')
        self.login_as(self.student)
        offending = self.send_class('Message blessant').json()['message']
        self.assertEqual(self.report('class', offending['id']).status_code, 400)  # son propre message

        self.login_as(self.classmate)
        self.assertEqual(self.report('class', offending['id']).status_code, 200)
        self.assertTrue(self.report('class', offending['id']).json()['already_reported'])
        report = ChatReport.objects.get()
        self.assertEqual(report.reported_user, self.student)
        self.assertEqual([item['body'] for item in report.snapshot], ['Contexte', 'Message blessant'])
        self.assertTrue(report.snapshot[-1]['reported'])

        self.login_as(self.teacher)
        page = self.client.get(reverse('chat:moderation'))
        self.assertContains(page, 'Message blessant')
        self.client.post(reverse('chat:moderation_action', args=[report.pk]), {'action': 'delete'})
        report.refresh_from_db()
        self.assertEqual(report.status, 'resolved')
        self.assertTrue(ChatMessage.objects.get(pk=offending['id']).is_deleted)

    def test_moderation_mute_action(self):
        self.login_as(self.student)
        offending = self.send_class('Spam').json()['message']
        self.login_as(self.classmate)
        self.report('class', offending['id'], 'spam')
        self.login_as(self.teacher)
        self.client.post(
            reverse('chat:moderation_action', args=[ChatReport.objects.get().pk]), {'action': 'mute'},
        )
        self.assertTrue(ChatMute.objects.filter(user=self.student, until__gt=timezone.now()).exists())

    def test_report_about_teacher_goes_to_admin_only(self):
        conversation = PrivateConversation.objects.create(
            classroom=self.classroom, student=self.student, teacher=self.teacher,
        )
        self.login_as(self.teacher)
        sent = self.post_json(
            reverse('chat:api_private_send', args=[conversation.pk]), {'body': 'Réponse'},
        ).json()['message']
        self.login_as(self.student)
        self.assertEqual(self.report('consultation', sent['id'], 'inappropriate').status_code, 200)
        self.login_as(self.teacher)
        self.assertNotContains(self.client.get(reverse('chat:moderation')), 'Réponse')
        self.login_as(self.admin)
        self.assertContains(self.client.get(reverse('chat:moderation')), 'Réponse')

    def test_other_teacher_cannot_see_or_handle_reports(self):
        self.login_as(self.student)
        offending = self.send_class('Hors sujet').json()['message']
        self.login_as(self.classmate)
        self.report('class', offending['id'], 'spam')
        self.login_as(self.other_teacher)
        self.assertNotContains(self.client.get(reverse('chat:moderation')), 'Hors sujet')
        response = self.client.post(
            reverse('chat:moderation_action', args=[ChatReport.objects.get().pk]), {'action': 'dismiss'},
        )
        self.assertEqual(response.status_code, 404)

    def test_students_cannot_open_moderation(self):
        self.login_as(self.student)
        self.assertEqual(self.client.get(reverse('chat:moderation')).status_code, 404)

    def test_unknown_kind_is_404(self):
        self.login_as(self.student)
        response = self.post_json(reverse('chat:api_message_report', args=['other', 1]), {'reason': 'spam'})
        self.assertEqual(response.status_code, 404)


class ConsultationContextTests(ChatTestBase):
    def setUp(self):
        super().setUp()
        course = Course.objects.create(name='Mathématiques', niveau='tronc_commun', order=1)
        self.lesson = Lesson.objects.create(course=course, order=1, title='Les suites', content='Une suite...')
        self.quiz = Quiz.objects.create(title='Quiz suites', lesson=self.lesson, created_by=self.other_teacher)
        self.question = Question.objects.create(quiz=self.quiz, text='Calculer $u_2$', order=3)
        self.conversation = PrivateConversation.objects.create(
            classroom=self.classroom, student=self.student, teacher=self.teacher,
        )
        self.send_url = reverse('chat:api_private_send', args=[self.conversation.pk])

    def test_question_must_belong_to_the_student_history(self):
        self.login_as(self.student)
        response = self.post_json(self.send_url, {'body': 'Je bloque', 'question_id': self.question.pk})
        self.assertEqual(response.status_code, 400)
        Attempt.objects.create(student=self.student, quiz=self.quiz, submitted_at=timezone.now(), score=40)
        response = self.post_json(self.send_url, {'body': 'Je bloque', 'question_id': self.question.pk})
        self.assertEqual(response.status_code, 200)
        context = response.json()['message']['context']
        self.assertEqual(context['kind'], 'question')
        self.assertIn('Question 3', context['label'])
        self.assertEqual(PrivateMessage.objects.get().lesson, self.lesson)

    def test_lesson_context(self):
        self.login_as(self.student)
        response = self.post_json(self.send_url, {'body': 'Cours ?', 'lesson_id': self.lesson.pk})
        self.assertEqual(response.json()['message']['context']['label'], 'Leçon : Les suites')

    def test_result_page_link_prefills_context(self):
        Attempt.objects.create(student=self.student, quiz=self.quiz, submitted_at=timezone.now(), score=40)
        self.login_as(self.student)
        response = self.client.get(
            reverse('chat:private_student_chat', args=[self.classroom.pk]), {'question': self.question.pk},
        )
        self.assertTrue(response.url.endswith(f'?question={self.question.pk}'))
        page = self.client.get(response.url)
        self.assertEqual(page.context['initial_context']['id'], self.question.pk)

    def test_teacher_can_open_consultation_from_results(self):
        self.login_as(self.teacher)
        response = self.client.get(reverse('chat:teacher_consult_student', args=[self.student.pk]))
        self.assertEqual(response.url, reverse('chat:private_room', args=[self.conversation.pk]))
        self.login_as(self.other_teacher)
        response = self.client.get(reverse('chat:teacher_consult_student', args=[self.student.pk]))
        self.assertEqual(response.url, reverse('quizzes:student_results'))


class AIDraftTests(ChatTestBase):
    def setUp(self):
        super().setUp()
        self.conversation = PrivateConversation.objects.create(
            classroom=self.classroom, student=self.student, teacher=self.teacher,
        )
        self.url = reverse('chat:api_ai_draft', args=[self.conversation.pk])

    def test_requires_a_student_question(self):
        self.login_as(self.teacher)
        self.assertEqual(self.post_json(self.url).status_code, 400)

    @patch('ai.providers.get_provider')
    def test_teacher_receives_draft_but_nothing_is_sent(self, get_provider):
        get_provider.return_value.chat.return_value = 'Commence par écrire $u_{n+1}-u_n$.'
        PrivateMessage.objects.create(conversation=self.conversation, sender=self.student, body='Comment montrer que la suite croît ?')
        self.login_as(self.teacher)
        response = self.post_json(self.url)
        self.assertEqual(response.json()['draft'], 'Commence par écrire $u_{n+1}-u_n$.')
        prompt = get_provider.return_value.chat.call_args[0][0][1]['content']
        self.assertIn('Comment montrer que la suite croît ?', prompt)
        self.assertEqual(PrivateMessage.objects.count(), 1)

    def test_student_and_other_teacher_cannot_request_drafts(self):
        PrivateMessage.objects.create(conversation=self.conversation, sender=self.student, body='?')
        for user in (self.student, self.other_teacher):
            self.login_as(user)
            self.assertEqual(self.post_json(self.url).status_code, 404)

    @patch('ai.providers.get_provider')
    def test_provider_failure_returns_friendly_error(self, get_provider):
        from ai.providers import AIProviderError
        get_provider.return_value.chat.side_effect = AIProviderError('down', code='unavailable')
        PrivateMessage.objects.create(conversation=self.conversation, sender=self.student, body='?')
        self.login_as(self.teacher)
        response = self.post_json(self.url)
        self.assertEqual(response.status_code, 503)
        self.assertIn('indisponible', response.json()['error'])


class UnreadCounterTests(ChatTestBase):
    def test_counts_all_kinds_and_ignores_deleted(self):
        from .context_processors import unread_total
        ChatMessage.objects.create(room=self.room, sender=self.teacher, body='Annonce')
        deleted = ChatMessage.objects.create(room=self.room, sender=self.teacher, body='Oups')
        deleted.soft_delete(self.teacher)
        conversation = PrivateConversation.objects.create(
            classroom=self.classroom, student=self.student, teacher=self.teacher,
        )
        PrivateMessage.objects.create(conversation=conversation, sender=self.teacher, body='Bonjour')
        self.assertEqual(unread_total(self.student), 2)

    def test_counter_does_not_create_rooms(self):
        other = Classroom.objects.create(name='TC9', niveau='tronc_commun', teacher=self.teacher)
        ClassroomMember.objects.create(classroom=other, user=self.student)
        self.login_as(self.student)
        self.client.get(reverse('accounts:profile'))
        self.assertFalse(ClassChatRoom.objects.filter(classroom=other).exists())


class AttachmentTests(ChatTestBase):
    def test_content_must_match_extension(self):
        self.login_as(self.student)
        response = self.client.post(reverse('chat:api_send', args=[self.classroom.pk]), {
            'attachment': SimpleUploadedFile('photo.png', b'<html>pas une image</html>', content_type='image/png'),
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn('ne correspond pas', response.json()['error'])

    def test_legacy_public_attachment_still_served_until_moved(self):
        legacy = Path(self.media_root) / 'chat' / '2026' / '10'
        legacy.mkdir(parents=True)
        (legacy / 'ancien.png').write_bytes(PNG)
        message = ChatMessage.objects.create(room=self.room, sender=self.teacher, attachment='chat/2026/10/ancien.png')
        self.login_as(self.student)
        response = self.client.get(reverse('chat:attachment', args=[message.pk]))
        self.assertEqual(response.status_code, 200)

        out = io.StringIO()
        call_command('move_class_chat_attachments', stdout=out)
        self.assertIn('1 fichier(s) à déplacer', out.getvalue())
        self.assertTrue((legacy / 'ancien.png').exists())
        call_command('move_class_chat_attachments', '--apply', stdout=io.StringIO())
        self.assertFalse((legacy / 'ancien.png').exists())
        self.assertEqual(self.client.get(reverse('chat:attachment', args=[message.pk])).status_code, 200)


class RetentionTests(ChatTestBase):
    def test_purge_is_a_dry_run_by_default(self):
        old = ChatMessage.objects.create(room=self.room, sender=self.teacher, body='Ancien')
        old.attachment.save('vieux.png', ContentFile(PNG), save=True)
        ChatMessage.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=400))
        removed = ChatMessage.objects.create(room=self.room, sender=self.teacher, body='x')
        removed.soft_delete(self.teacher)
        ChatMessage.objects.filter(pk=removed.pk).update(deleted_at=timezone.now() - timedelta(days=40))

        out = io.StringIO()
        call_command('purge_chat_data', stdout=out)
        self.assertIn('[simulation] 1 fichier(s)', out.getvalue())
        self.assertTrue(ChatMessage.objects.filter(pk=removed.pk).exists())

        call_command('purge_chat_data', '--apply', stdout=io.StringIO())
        old.refresh_from_db()
        self.assertFalse(old.attachment)
        self.assertIn('durée de conservation', old.body)
        self.assertFalse(ChatMessage.objects.filter(pk=removed.pk).exists())


class WhiteboardShareChatTests(ChatTestBase):
    def test_share_is_posted_in_class_chat(self):
        from PIL import Image
        buffer = io.BytesIO()
        Image.new('RGB', (4, 4), 'white').save(buffer, format='PNG')
        self.login_as(self.teacher)
        response = self.client.post(reverse('whiteboard:share_create'), {
            'classroom_id': self.classroom.pk,
            'title': 'Correction ex. 3',
            'image': SimpleUploadedFile('board.png', buffer.getvalue(), content_type='image/png'),
        })
        self.assertEqual(response.status_code, 200)
        self.login_as(self.student)
        messages = self.client.get(reverse('chat:api_messages', args=[self.classroom.pk])).json()['messages']
        self.assertEqual(messages[-1]['whiteboard_share']['title'], 'Correction ex. 3')


class WebSocketAuthTests(TestCase):
    def test_inactive_or_outdated_sessions_are_refused(self):
        from asgiref.sync import async_to_sync
        from .middleware import get_user
        user = User.objects.create_user(username='ws', email='ws@example.test', role='student')
        self.assertEqual(async_to_sync(get_user)(user.pk, 0), user)
        self.assertIsNone(async_to_sync(get_user)(user.pk, 1))
        user.is_active = False
        user.save()
        self.assertIsNone(async_to_sync(get_user)(user.pk, 0))
