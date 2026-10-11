from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User, StudentProfile
from education.models import Course, Lesson
from quizzes.models import Quiz, Question, Attempt, StudentAnswer
from .models import Classroom, ClassroomMember


@override_settings(ALLOWED_HOSTS=['testserver'])
class RejectClassMembersTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(
            username='member-teacher', email='member-teacher@example.test', role='teacher',
        )
        self.other_teacher = User.objects.create_user(
            username='other-teacher', email='other-teacher@example.test', role='teacher',
        )
        self.classroom = Classroom.objects.create(name='Classe A', teacher=self.teacher)
        self.other_classroom = Classroom.objects.create(name='Classe B', teacher=self.other_teacher)
        self.members = []
        for index in range(3):
            student = User.objects.create_user(
                username=f'member-{index}', email=f'member-{index}@example.test', role='student',
            )
            StudentProfile.objects.create(user=student)
            self.members.append(ClassroomMember.objects.create(
                classroom=self.classroom if index < 2 else self.other_classroom, user=student,
            ))
        course = Course.objects.create(name='Test', niveau='tronc_commun')
        lesson = Lesson.objects.create(course=course, title='Test')
        quiz = Quiz.objects.create(title='Test', lesson=lesson, created_by=self.teacher)
        question = Question.objects.create(quiz=quiz, text='1+1', correct_answer='2')
        self.attempt = Attempt.objects.create(
            quiz=quiz, student=self.members[0].user, submitted_at=timezone.now(), score=100,
        )
        self.answer = StudentAnswer.objects.create(
            attempt=self.attempt, question=question, answer='2', is_correct=True,
        )
        self.url = reverse('classrooms:reject_class_members', args=[self.classroom.pk])
        self.login(self.teacher)

    def login(self, user, client=None):
        session = (client or self.client).session
        session['user_id'] = user.pk
        session.save()

    def test_selected_memberships_removed_accounts_and_results_preserved(self):
        response = self.client.post(self.url, {
            'membership_ids': [self.members[0].pk, self.members[1].pk],
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Élèves (0)')
        self.assertFalse(self.classroom.members.exists())
        self.assertTrue(ClassroomMember.objects.filter(pk=self.members[2].pk).exists())
        self.assertEqual(User.objects.filter(role='student').count(), 3)
        self.assertEqual(StudentProfile.objects.count(), 3)
        self.assertTrue(Attempt.objects.filter(pk=self.attempt.pk, score=100).exists())
        self.assertTrue(StudentAnswer.objects.filter(pk=self.answer.pk, answer='2').exists())

    def test_selected_student_disappears_from_teacher_students_and_class_list(self):
        response = self.client.post(reverse('classrooms:reject_members'), {
            'membership_ids': [self.members[0].pk],
        }, follow=True)
        self.assertNotContains(response, self.members[0].user.username)
        self.assertContains(response, self.members[1].user.username)
        self.assertEqual(self.classroom.members.count(), 1)
        self.assertContains(
            self.client.get(reverse('classrooms:list')), 'Classe A',
        )

    def test_removal_does_not_remove_membership_in_another_class(self):
        second = ClassroomMember.objects.create(
            classroom=self.other_classroom, user=self.members[0].user,
        )
        self.client.post(self.url, {'membership_ids': [self.members[0].pk]})
        self.assertTrue(ClassroomMember.objects.filter(pk=second.pk).exists())

    def test_forged_foreign_member_aborts_entire_selection(self):
        response = self.client.post(self.url, {
            'membership_ids': [self.members[0].pk, self.members[2].pk],
        })
        self.assertEqual(response.status_code, 404)
        self.assertEqual(ClassroomMember.objects.count(), 3)

    def test_other_teacher_cannot_reject_members(self):
        self.login(self.other_teacher)
        self.assertEqual(self.client.post(self.url, {
            'membership_ids': [self.members[0].pk],
        }).status_code, 404)
        self.assertEqual(self.classroom.members.count(), 2)

    def test_students_cannot_reject_and_controls_are_teacher_only(self):
        self.login(self.members[0].user)
        response = self.client.get(reverse('classrooms:detail', args=[self.classroom.pk]))
        self.assertNotContains(response, 'rejectMembersForm')
        response = self.client.post(self.url, {'membership_ids': [self.members[1].pk]})
        self.assertRedirects(response, reverse('education:home'), fetch_redirect_response=False)
        self.assertEqual(self.classroom.members.count(), 2)

    def test_get_and_missing_csrf_cannot_remove_members(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        client = Client(enforce_csrf_checks=True)
        self.login(self.teacher, client)
        self.assertEqual(client.post(self.url, {
            'membership_ids': [self.members[0].pk],
        }).status_code, 403)
        self.assertEqual(self.classroom.members.count(), 2)

    def test_empty_or_invalid_selection_does_not_delete_anything(self):
        response = self.client.post(self.url, {}, follow=True)
        self.assertContains(response, 'Sélectionnez au moins un élève.')
        for value in ('not-an-id', '0', '999999'):
            self.assertEqual(self.client.post(self.url, {
                'membership_ids': [value],
            }).status_code, 404)
        self.assertEqual(ClassroomMember.objects.count(), 3)

    def test_class_endpoint_cannot_remove_members_from_another_owned_class(self):
        other_owned = Classroom.objects.create(name='Classe C', teacher=self.teacher)
        extra = ClassroomMember.objects.create(classroom=other_owned, user=self.members[2].user)
        self.assertEqual(self.client.post(self.url, {
            'membership_ids': [extra.pk],
        }).status_code, 404)
        self.assertTrue(ClassroomMember.objects.filter(pk=extra.pk).exists())

    def test_repeated_request_does_not_delete_accounts(self):
        self.client.post(self.url, {'membership_ids': [self.members[0].pk]})
        self.assertEqual(self.client.post(self.url, {
            'membership_ids': [self.members[0].pk],
        }).status_code, 404)
        self.assertTrue(User.objects.filter(pk=self.members[0].user_id).exists())
