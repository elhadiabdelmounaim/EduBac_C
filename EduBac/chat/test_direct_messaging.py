import json

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from classrooms.models import Classroom, ClassroomMember
from .models import (
    ChatMessage,
    ChatPresence,
    DirectConversation,
    DirectMessage,
    PrivateConversation,
)


@override_settings(ALLOWED_HOSTS=['testserver'])
class DirectMessagingTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(
            username='direct_teacher',
            email='direct-teacher@example.test',
            role='teacher',
        )
        self.student = User.objects.create_user(
            username='direct_student',
            email='direct-student@example.test',
            first_name='Samira',
            last_name='Élève',
            role='student',
        )
        self.classmate = User.objects.create_user(
            username='direct_classmate',
            email='direct-classmate@example.test',
            first_name='Youssef',
            last_name='Camarade',
            role='student',
        )
        self.outsider = User.objects.create_user(
            username='direct_outsider',
            email='direct-outsider@example.test',
            role='student',
        )
        self.admin = User.objects.create_superuser(
            username='direct_admin',
            email='direct-admin@example.test',
            password='unused-test-password',
        )
        self.second_admin = User.objects.create_user(
            username='direct_staff',
            email='direct-staff@example.test',
            role='teacher',
            is_staff=True,
        )
        self.classroom = Classroom.objects.create(
            name='1BAC-SM-2026',
            niveau='1ere_bac_sm',
            teacher=self.teacher,
            is_active=True,
        )
        self.other_class = Classroom.objects.create(
            name='2BAC-PC-2026',
            niveau='2eme_bac_pc',
            teacher=None,
            is_active=True,
        )
        ClassroomMember.objects.create(classroom=self.classroom, user=self.student)
        ClassroomMember.objects.create(classroom=self.classroom, user=self.classmate)
        ClassroomMember.objects.create(classroom=self.other_class, user=self.outsider)

    def login_as(self, user):
        session = self.client.session
        session['user_id'] = user.pk
        session.save()

    def post_json(self, url, data):
        return self.client.post(
            url,
            data=json.dumps(data),
            content_type='application/json',
            HTTP_ACCEPT='application/json',
        )

    def start_direct(self, contact):
        return self.post_json(
            reverse('chat:api_direct_start'),
            {'user_id': contact.pk},
        )

    def test_student_contacts_are_limited_to_teacher_admin_and_same_classmates(self):
        self.login_as(self.student)

        response = self.client.get(
            reverse('chat:api_direct_contacts'),
            HTTP_ACCEPT='application/json',
        )
        self.assertEqual(response.status_code, 200)
        contacts = response.json()['contacts']
        contact_ids = {contact['id'] for contact in contacts}
        self.assertIn(self.teacher.pk, contact_ids)
        self.assertIn(self.admin.pk, contact_ids)
        self.assertIn(self.classmate.pk, contact_ids)
        self.assertNotIn(self.outsider.pk, contact_ids)
        self.assertEqual(len(contact_ids), len(contacts))
        filtered = self.client.get(
            reverse('chat:api_direct_contacts'),
            {'q': '1BAC-SM'},
            HTTP_ACCEPT='application/json',
        )
        self.assertIn(
            self.classmate.pk,
            {contact['id'] for contact in filtered.json()['contacts']},
        )

    def test_student_peer_conversation_is_unique_and_read_receipts_work(self):
        self.login_as(self.student)
        first_start = self.start_direct(self.classmate)
        second_start = self.start_direct(self.classmate)

        self.assertEqual(first_start.status_code, 200)
        self.assertEqual(first_start.json()['url'], second_start.json()['url'])
        self.assertEqual(DirectConversation.objects.count(), 1)
        conversation = DirectConversation.objects.get()

        sent = self.post_json(
            reverse('chat:api_direct_send', args=[conversation.pk]),
            {'body': 'Bonjour, camarade.'},
        )
        self.assertEqual(sent.status_code, 200)
        self.login_as(self.classmate)
        read = self.client.get(
            reverse('chat:api_direct_messages', args=[conversation.pk]),
            HTTP_ACCEPT='application/json',
        )
        self.assertTrue(read.json()['messages'][0]['is_read'])
        self.login_as(self.student)
        receipts = self.client.get(
            reverse('chat:api_direct_messages', args=[conversation.pk]),
            {'after_id': sent.json()['message']['id']},
            HTTP_ACCEPT='application/json',
        )
        self.assertIn(sent.json()['message']['id'], receipts.json()['read_ids'])

    def test_student_cannot_start_a_direct_chat_with_another_class(self):
        self.login_as(self.student)

        response = self.start_direct(self.outsider)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(DirectConversation.objects.count(), 0)

    def test_student_cannot_read_a_direct_conversation_after_losing_class_access(self):
        conversation, _ = DirectConversation.get_or_create_for(
            self.student,
            self.outsider,
            classroom=self.other_class,
        )
        self.login_as(self.student)

        response = self.client.get(
            reverse('chat:api_direct_messages', args=[conversation.pk]),
            HTTP_ACCEPT='application/json',
        )

        self.assertEqual(response.status_code, 404)

    def test_peer_chat_remains_available_while_another_shared_class_is_active(self):
        shared_class = Classroom.objects.create(
            name='1BAC-SM-Supplementaire',
            niveau='1ere_bac_sm',
            teacher=self.teacher,
            is_active=True,
        )
        ClassroomMember.objects.create(classroom=shared_class, user=self.student)
        ClassroomMember.objects.create(classroom=shared_class, user=self.classmate)
        conversation, _ = DirectConversation.get_or_create_for(
            self.student,
            self.classmate,
            classroom=self.classroom,
        )
        ClassroomMember.objects.filter(
            classroom=self.classroom,
            user=self.student,
        ).delete()
        self.login_as(self.student)

        response = self.client.get(
            reverse('chat:api_direct_messages', args=[conversation.pk]),
            HTTP_ACCEPT='application/json',
        )

        self.assertEqual(response.status_code, 200)

    def test_admin_can_reply_to_student_admin_inbox(self):
        self.login_as(self.student)
        started = self.start_direct(self.admin)
        self.assertEqual(started.status_code, 200)
        conversation = DirectConversation.objects.get()
        student_message = self.post_json(
            reverse('chat:api_direct_send', args=[conversation.pk]),
            {'body': 'J’ai une question sur les cours.'},
        )
        self.assertEqual(student_message.status_code, 200)

        self.login_as(self.second_admin)
        inbox = self.client.get(reverse('chat:home'))
        self.assertContains(inbox, 'Samira Élève')
        reply = self.post_json(
            reverse('chat:api_direct_send', args=[conversation.pk]),
            {'body': 'Nous allons vous aider.'},
        )
        self.assertEqual(reply.status_code, 200)
        self.assertEqual(DirectMessage.objects.count(), 2)

    def test_teacher_can_start_consultations_only_with_own_class_students(self):
        self.login_as(self.teacher)
        contacts = self.client.get(
            reverse('chat:api_direct_contacts'),
            HTTP_ACCEPT='application/json',
        ).json()['contacts']
        contact_ids = {contact['id'] for contact in contacts}
        self.assertIn(self.student.pk, contact_ids)
        self.assertIn(self.classmate.pk, contact_ids)
        self.assertNotIn(self.outsider.pk, contact_ids)

        started = self.start_direct(self.student)

        self.assertEqual(started.status_code, 200)
        self.assertEqual(started.json()['kind'], 'consultation')
        self.assertEqual(PrivateConversation.objects.count(), 1)

    def test_teacher_can_choose_the_right_class_for_a_student_consultation(self):
        second_class = Classroom.objects.create(
            name='2BAC-SM-2026',
            niveau='2eme_bac_sm',
            teacher=self.teacher,
            is_active=True,
        )
        ClassroomMember.objects.create(classroom=second_class, user=self.student)
        self.login_as(self.teacher)

        contacts = self.client.get(
            reverse('chat:api_direct_contacts'),
            HTTP_ACCEPT='application/json',
        ).json()['contacts']
        student_contacts = [
            contact for contact in contacts
            if contact['id'] == self.student.pk
        ]
        self.assertEqual(
            {contact['classroom_id'] for contact in student_contacts},
            {self.classroom.pk, second_class.pk},
        )
        second_class_contact = next(
            contact for contact in student_contacts
            if contact['classroom_id'] == second_class.pk
        )
        started = self.post_json(
            reverse('chat:api_direct_start'),
            {
                'user_id': self.student.pk,
                'classroom_id': second_class_contact['classroom_id'],
            },
        )

        self.assertEqual(started.status_code, 200)
        self.assertEqual(
            PrivateConversation.objects.get().classroom_id,
            second_class.pk,
        )

    def test_admin_sees_all_real_classes_and_students_cannot_see_other_groups(self):
        inactive = Classroom.objects.create(
            name='Classe archivée',
            niveau='2eme_bac_pc',
            teacher=self.teacher,
            is_active=False,
        )
        self.login_as(self.admin)
        admin_home = self.client.get(reverse('chat:home'))
        self.assertEqual(admin_home.status_code, 200)
        self.assertContains(admin_home, inactive.name)
        self.assertEqual(len(admin_home.context['rooms']), 3)

        self.login_as(self.student)
        student_home = self.client.get(reverse('chat:home'))
        self.assertContains(student_home, self.classroom.name)
        self.assertNotContains(student_home, self.other_class.name)
        self.assertNotContains(student_home, inactive.name)

    def test_announcement_and_participation_follow_class_permissions(self):
        self.login_as(self.student)
        student_announcement = self.post_json(
            reverse('chat:api_send', args=[self.classroom.pk]),
            {'body': 'Annonce non autorisée', 'is_announcement': True},
        )
        self.assertEqual(student_announcement.status_code, 403)

        self.login_as(self.teacher)
        teacher_announcement = self.post_json(
            reverse('chat:api_send', args=[self.classroom.pk]),
            {'body': 'Révision vendredi', 'is_announcement': True},
        )
        self.assertEqual(teacher_announcement.status_code, 200)
        self.assertTrue(teacher_announcement.json()['message']['is_announcement'])
        self.assertTrue(ChatMessage.objects.get().is_announcement)

        members = self.client.get(
            reverse('chat:api_room_members', args=[self.classroom.pk]),
            HTTP_ACCEPT='application/json',
        )
        self.assertEqual(members.status_code, 200)
        entries = {member['id']: member for member in members.json()['members']}
        self.assertEqual(entries[self.teacher.pk]['message_count'], 1)
        self.assertIn(self.classmate.pk, entries)

        self.login_as(self.outsider)
        denied = self.client.get(
            reverse('chat:api_room_members', args=[self.classroom.pk]),
            HTTP_ACCEPT='application/json',
        )
        self.assertEqual(denied.status_code, 404)

    def test_presence_updates_online_status(self):
        self.login_as(self.classmate)

        response = self.client.post(
            reverse('chat:api_presence'),
            HTTP_ACCEPT='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(ChatPresence.objects.filter(user=self.classmate).exists())
        self.login_as(self.student)
        contact = next(
            item for item in self.client.get(
                reverse('chat:api_direct_contacts'),
                HTTP_ACCEPT='application/json',
            ).json()['contacts']
            if item['id'] == self.classmate.pk
        )
        self.assertTrue(contact['is_online'])

    def test_messaging_pages_render_role_controls(self):
        self.login_as(self.teacher)

        inbox = self.client.get(reverse('chat:home'))
        self.assertEqual(inbox.status_code, 200)
        self.assertContains(inbox, 'id="messageTabs"')
        self.assertContains(inbox, 'id="classFilter"')
        self.assertContains(inbox, 'id="newConversationDialog"')

        legacy_inbox = self.client.get(reverse('chat:private_inbox'))
        self.assertEqual(legacy_inbox.status_code, 200)
        self.assertContains(legacy_inbox, 'data-active-tab="individuals"')

        group = self.client.get(
            reverse('chat:room', args=[self.classroom.pk]),
        )
        self.assertEqual(group.status_code, 200)
        self.assertContains(group, 'id="chatMembersBtn"')
        self.assertContains(group, 'id="chatAnnouncementInput"')
