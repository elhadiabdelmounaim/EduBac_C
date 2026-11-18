from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from classrooms.models import Classroom, ClassroomMember
from education.models import Course, Lesson
from notifications.models import Notification
from quizzes.models import Attempt, Quiz, QuizAssignment


class TeacherFollowUpTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create(username='prof', email='p@t.test', role='teacher')
        self.done = User.objects.create(username='done', email='d@t.test', first_name='Dina')
        self.late = User.objects.create(username='late', email='l@t.test', first_name='Lina')
        self.classroom = Classroom.objects.create(name='1bac1', niveau='1ere_bac_sc', teacher=self.teacher)
        for student in (self.done, self.late):
            self.classroom.add_member(student)
        lesson = Lesson.objects.create(course=Course.objects.create(name='Maths', niveau='1ere_bac_sc'),
                                       title='Fonctions', order=1)
        self.quiz = Quiz.objects.create(title='Fonctions', lesson=lesson, created_by=self.teacher,
                                        status='published', classroom=self.classroom)
        for student in (self.done, self.late):
            QuizAssignment.objects.create(quiz=self.quiz, student=student)
        Attempt.objects.create(student=self.done, quiz=self.quiz, score=80, submitted_at=timezone.now())
        session = self.client.session
        session['user_id'] = self.teacher.pk
        session.save()

    def test_remind_only_students_who_have_not_submitted(self):
        Notification.objects.all().delete()
        response = self.client.post(reverse('quizzes:remind_pending', args=[self.quiz.pk]), follow=True)
        self.assertContains(response, 'Rappel envoyé à 1 élève(s)')
        reminded = Notification.objects.filter(title='Rappel du professeur')
        self.assertEqual([n.recipient for n in reminded], [self.late])
        # Une deuxième relance remplace la première au lieu d'en empiler.
        self.client.post(reverse('quizzes:remind_pending', args=[self.quiz.pk]))
        self.assertEqual(Notification.objects.filter(title='Rappel du professeur', is_read=False).count(), 1)

    def test_other_teacher_cannot_remind(self):
        other = User.objects.create(username='autre', email='a@t.test', role='teacher')
        session = self.client.session
        session['user_id'] = other.pk
        session.save()
        self.client.post(reverse('quizzes:remind_pending', args=[self.quiz.pk]))
        self.assertFalse(Notification.objects.filter(title='Rappel du professeur').exists())

    def test_dashboard_lists_inactive_students(self):
        ClassroomMember.objects.update(joined_at=timezone.now() - timedelta(days=30))
        Attempt.objects.update(submitted_at=timezone.now() - timedelta(days=2))
        page = self.client.get(reverse('accounts:teacher_portal'))
        self.assertContains(page, '1 élève sans activité depuis 2 semaines')
        self.assertContains(page, 'Lina')
