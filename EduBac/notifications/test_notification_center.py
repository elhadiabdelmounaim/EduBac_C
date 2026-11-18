"""Centre de notifications : regroupement, préférences, résumé, nouveaux événements."""
import io
import json
from datetime import timedelta

from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from chat.models import ClassChatRoom, PrivateConversation
from classrooms.models import Classroom, ClassroomMember
from education.models import Course, Lesson
from quizzes.models import Attempt, Quiz, QuizAssignment

from .models import Notification, NotificationPreference


@override_settings(
    ALLOWED_HOSTS=['testserver'],
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    EMAIL_NOTIFICATIONS_ENABLED=True,
    DEFAULT_FROM_EMAIL='edubac@example.test',
)
class NotificationCenterBase(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(
            username='prof', email='prof@example.test', role='teacher', first_name='Nadia',
        )
        # Comme à l'inscription réelle : les élèves n'ont pas d'adresse e-mail.
        self.student = User.objects.create(username='amal', email=None, role='student', first_name='Amal')
        self.other = User.objects.create(username='badr', email=None, role='student', first_name='Badr')
        self.classroom = Classroom.objects.create(name='TC1', niveau='tronc_commun', teacher=self.teacher)
        ClassroomMember.objects.create(classroom=self.classroom, user=self.student)
        ClassroomMember.objects.create(classroom=self.classroom, user=self.other)
        course = Course.objects.create(name='Mathématiques', niveau='tronc_commun', order=1)
        self.lesson = Lesson.objects.create(course=course, order=1, title='Logique', content='x')
        self.quiz = Quiz.objects.create(
            title='Quiz logique', lesson=self.lesson, created_by=self.teacher, status='published',
        )
        Notification.objects.all().delete()
        mail.outbox.clear()

    def login_as(self, user):
        session = self.client.session
        session['user_id'] = user.pk
        session.save()

    def finish(self, student, score):
        attempt = Attempt.objects.create(student=student, quiz=self.quiz)
        attempt.submitted_at = timezone.now()
        attempt.score = score
        attempt.save()
        return attempt


class GroupingTests(NotificationCenterBase):
    def test_teacher_gets_one_grouped_notification_per_quiz(self):
        QuizAssignment.objects.create(quiz=self.quiz, student=self.student)
        QuizAssignment.objects.create(quiz=self.quiz, student=self.other)
        Notification.objects.all().delete()
        self.finish(self.student, 80)
        self.finish(self.other, 40)
        teacher_notes = Notification.objects.filter(recipient=self.teacher, type='quiz_result')
        self.assertEqual(teacher_notes.count(), 1)
        note = teacher_notes.get()
        self.assertEqual(note.count, 2)
        self.assertIn('2/2', note.message)
        self.assertIn('60.0', note.message)
        # Chaque élève reçoit son propre résultat.
        self.assertEqual(Notification.objects.filter(recipient=self.student, type='quiz_result').count(), 1)

    def test_a_read_group_starts_a_new_notification(self):
        self.finish(self.student, 80)
        Notification.objects.filter(recipient=self.teacher).update(is_read=True)
        self.finish(self.other, 50)
        self.assertEqual(Notification.objects.filter(recipient=self.teacher, type='quiz_result').count(), 2)


class PreferenceAndEmailTests(NotificationCenterBase):
    def test_teacher_quiz_results_go_to_digest_not_instant_email(self):
        self.finish(self.student, 80)
        self.finish(self.other, 40)
        self.assertEqual(mail.outbox, [])
        note = Notification.objects.get(recipient=self.teacher, type='quiz_result')
        self.assertEqual(note.email_status, Notification.EMAIL_DIGEST)

        out = io.StringIO()
        call_command('send_notification_digest', stdout=out)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Quiz logique', mail.outbox[0].body)
        note.refresh_from_db()
        self.assertEqual(note.email_status, Notification.EMAIL_SENT)
        call_command('send_notification_digest', stdout=io.StringIO())
        self.assertEqual(len(mail.outbox), 1)

    def test_digest_skips_notifications_already_read(self):
        self.finish(self.student, 80)
        Notification.objects.filter(recipient=self.teacher).update(is_read=True)
        call_command('send_notification_digest', stdout=io.StringIO())
        self.assertEqual(mail.outbox, [])
        self.assertFalse(Notification.objects.filter(email_status=Notification.EMAIL_DIGEST).exists())

    def test_instant_email_and_preferences_override(self):
        from notifications.services import notify_report

        class Report:
            def get_reason_display(self):
                return 'Spam'

        notify_report(Report(), [self.teacher])
        self.assertEqual(len(mail.outbox), 1)

        NotificationPreference.objects.create(
            user=self.teacher, values={'moderation': {'in_app': False, 'email': 'off'}},
        )
        Notification.objects.all().delete()
        notify_report(Report(), [self.teacher])
        self.assertEqual(len(mail.outbox), 1)
        note = Notification.objects.get(recipient=self.teacher)
        self.assertTrue(note.is_read)  # rangée dans l'historique sans badge

    def test_bulk_notifications_respect_muted_type(self):
        from notifications.services import notify_class_announcement
        from chat.models import ChatMessage
        NotificationPreference.objects.create(user=self.other, values={'message': {'in_app': False}})
        room = ClassChatRoom.get_or_create_for(self.classroom)
        message = ChatMessage.objects.create(room=room, sender=self.teacher, body='Contrôle lundi', is_announcement=True)
        notify_class_announcement(message)
        self.assertFalse(Notification.objects.get(recipient=self.student).is_read)
        self.assertTrue(Notification.objects.get(recipient=self.other).is_read)
        self.assertFalse(Notification.objects.filter(recipient=self.teacher).exists())

    def test_preferences_page(self):
        self.login_as(self.teacher)
        page = self.client.get(reverse('notifications:preferences'))
        self.assertTrue(page.context['has_email'])
        codes = [row['code'] for row in page.context['rows']]
        self.assertIn('moderation', codes)
        self.assertNotIn('comment', codes)
        self.client.post(reverse('notifications:preferences'), {
            'in_app_quiz_result': 'on', 'email_quiz_result': 'off',
        })
        self.assertEqual(
            NotificationPreference.for_user(self.teacher, 'quiz_result'), {'in_app': True, 'email': 'off'},
        )
        self.assertFalse(NotificationPreference.for_user(self.teacher, 'message')['in_app'])

        self.login_as(self.student)
        page = self.client.get(reverse('notifications:preferences'))
        self.assertFalse(page.context['has_email'])
        self.assertNotContains(page, 'Résumé quotidien')


class NewEventTests(NotificationCenterBase):
    def test_teacher_comment_notifies_student_once_per_change(self):
        attempt = self.finish(self.student, 70)
        Notification.objects.all().delete()
        self.login_as(self.teacher)
        url = reverse('quizzes:comment', args=[attempt.pk])
        self.client.post(url, {'comment': 'Revois la contraposée.'})
        self.client.post(url, {'comment': 'Revois la contraposée.'})
        notes = Notification.objects.filter(recipient=self.student, type='comment')
        self.assertEqual(notes.count(), 1)
        self.assertEqual(notes.get().link, reverse('quizzes:results', args=[attempt.pk]))

    def test_registration_flow(self):
        admin = User.objects.create_superuser(username='root', email='root@example.test', password='x')
        response = self.client.post(reverse('accounts:register_student'), {
            'name': 'Sara Nouvelle', 'username': 'sara', 'password': 'Motdepasse-123',
            'password2': 'Motdepasse-123', 'class_code': self.classroom.code,
        })
        self.assertEqual(response.status_code, 302)
        sara = User.objects.get(username='sara')
        self.assertTrue(Notification.objects.filter(recipient=admin, type='account').exists())
        # Le professeur n'est pas prévenu d'une inscription non validée.
        self.assertFalse(Notification.objects.filter(recipient=self.teacher, type='classroom').exists())

        self.login_as(admin)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('accounts:review_registration', args=[sara.pk]), {'action': 'approve'})
        self.assertTrue(Notification.objects.filter(recipient=sara, type='account').exists())
        self.assertTrue(Notification.objects.filter(recipient=self.teacher, type='classroom').exists())

    def test_consultation_messages_are_grouped_and_cleared_on_open(self):
        conversation = PrivateConversation.objects.create(
            classroom=self.classroom, student=self.student, teacher=self.teacher,
        )
        self.login_as(self.student)
        send = reverse('chat:api_private_send', args=[conversation.pk])
        for body in ('Bonjour', 'Je bloque sur l’exercice 2'):
            self.client.post(send, data=json.dumps({'body': body}), content_type='application/json')
        note = Notification.objects.get(recipient=self.teacher, type='message')
        self.assertEqual(note.count, 2)
        self.assertIn('exercice 2', note.message)

        self.login_as(self.teacher)
        self.client.get(reverse('chat:api_private_messages', args=[conversation.pk]))
        note.refresh_from_db()
        self.assertTrue(note.is_read)

    def test_deadline_reminders_and_missed_alerts_are_sent_once(self):
        from notifications.reminders import send_deadline_reminders, send_missed_deadline_alerts
        QuizAssignment.objects.create(
            quiz=self.quiz, student=self.student, deadline=timezone.now() + timedelta(hours=10),
        )
        late_quiz = Quiz.objects.create(title='Quiz en retard', lesson=self.lesson, created_by=self.teacher)
        QuizAssignment.objects.create(
            quiz=late_quiz, student=self.student, deadline=timezone.now() - timedelta(hours=2),
        )
        QuizAssignment.objects.create(
            quiz=late_quiz, student=self.other, deadline=timezone.now() - timedelta(hours=2),
        )
        self.finish_late = Attempt.objects.create(
            student=self.other, quiz=late_quiz, submitted_at=timezone.now(), score=50,
        )
        Notification.objects.all().delete()
        self.assertEqual(send_deadline_reminders(), 1)
        self.assertEqual(send_deadline_reminders(), 0)
        self.assertEqual(send_missed_deadline_alerts(), 1)
        self.assertEqual(send_missed_deadline_alerts(), 0)
        alert = Notification.objects.get(recipient=self.teacher, type='quiz_missed')
        self.assertIn('1 élève(s)', alert.message)
        self.assertIn('Amal', alert.message)

    def test_scheduled_publication_goes_to_the_chosen_class_and_notifies_author(self):
        draft = Quiz.objects.create(
            title='Programmé', lesson=self.lesson, created_by=self.teacher, status='draft',
            publish_at=timezone.now() - timedelta(minutes=1), classroom=self.classroom,
        )
        self.login_as(self.teacher)
        self.client.get(reverse('quizzes:manage'))
        draft.refresh_from_db()
        self.assertEqual(draft.status, 'published')
        self.assertEqual(set(draft.assignments.values_list('student', flat=True)), {self.student.pk, self.other.pk})
        self.assertTrue(Notification.objects.filter(recipient=self.student, title='Nouveau quiz assigné').exists())
        self.assertTrue(Notification.objects.filter(recipient=self.teacher, title='Quiz publié').exists())

    def test_scheduled_publication_without_class_stays_draft_and_warns_author(self):
        draft = Quiz.objects.create(
            title='Sans classe', lesson=self.lesson, created_by=self.teacher, status='draft',
            publish_at=timezone.now() - timedelta(minutes=1),
        )
        self.login_as(self.teacher)
        self.client.get(reverse('quizzes:manage'))
        draft.refresh_from_db()
        self.assertEqual(draft.status, 'draft', 'jamais publié pour personne')
        self.assertIsNone(draft.publish_at)
        self.assertTrue(Notification.objects.filter(recipient=self.teacher, title='Quiz non envoyé').exists())


class HistoryPageTests(NotificationCenterBase):
    def test_history_lists_read_notifications_with_filters(self):
        Notification.notify(self.student, 'Lue', 'x', type='comment', link='/quizzes/assignes/', send_email=False)
        Notification.objects.update(is_read=True)
        Notification.notify(self.student, 'Non lue', 'y', type='quiz_assigned', send_email=False)
        self.login_as(self.student)
        page = self.client.get(reverse('notifications:history'))
        self.assertContains(page, 'Lue')
        self.assertContains(page, 'Non lue')
        filtered = self.client.get(reverse('notifications:history'), {'type': 'comment'})
        self.assertEqual([n.title for n in filtered.context['page_obj']], ['Lue'])
        unread = self.client.get(reverse('notifications:history'), {'etat': 'non-lues'})
        self.assertEqual([n.title for n in unread.context['page_obj']], ['Non lue'])

    def test_open_marks_read_and_never_redirects_off_site(self):
        safe = Notification.notify(self.student, 'A', 'x', link='/quizzes/assignes/', send_email=False)
        unsafe = Notification.notify(self.student, 'B', 'x', link='//evil.example/', send_email=False)
        self.login_as(self.student)
        response = self.client.post(reverse('notifications:open', args=[safe.pk]))
        self.assertEqual(response.url, '/quizzes/assignes/')
        safe.refresh_from_db()
        self.assertTrue(safe.is_read)
        response = self.client.post(reverse('notifications:open', args=[unsafe.pk]))
        self.assertEqual(response.url, reverse('notifications:history'))
        self.login_as(self.other)
        self.assertEqual(self.client.post(reverse('notifications:open', args=[safe.pk])).status_code, 404)

    def test_api_list_ignores_invalid_limit(self):
        self.login_as(self.student)
        response = self.client.get(reverse('notifications:api_list'), {'limit': 'abc'})
        self.assertEqual(response.status_code, 200)
