import json

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from classrooms.models import Classroom, ClassroomMember
from .models import PrivateConversation, PrivateMessage


@override_settings(ALLOWED_HOSTS=['testserver'])
class PrivateConsultationTests(TestCase):
    def setUp(self):
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
        self.assertEqual(
            self.client.get(
                reverse('chat:api_private_messages', args=[conversation.pk]),
            ).status_code,
            404,
        )
        self.assertEqual(self.client.get(reverse('chat:private_inbox')).status_code, 403)

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
