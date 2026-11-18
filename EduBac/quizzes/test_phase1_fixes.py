"""Tests de non-régression des corrections critiques de la phase 1 (audit)."""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import DailyActivity, User
from classrooms.models import Classroom
from education.models import Course, Lesson
from notifications.models import Notification
from quizzes.models import Attempt, Choice, Question, Quiz, QuizAssignment, StudentAnswer


def make_user(username, role, **extra):
    user = User(username=username, email=f'{username}@example.test', role=role, **extra)
    user.set_password('pass12345')
    user.save()
    return user


def make_quiz(owner, lesson, title='Quiz', questions=2, status='draft'):
    quiz = Quiz.objects.create(
        title=title, lesson=lesson, created_by=owner, status=status,
        seconds_per_question=20, question_count=questions,
    )
    for order in range(1, questions + 1):
        question = Question.objects.create(
            quiz=quiz, text=f'Question {order}', correct_answer='A',
            order=order, points=Decimal('2.00'), difficulty='difficile',
        )
        Choice.objects.create(question=question, text='A', is_correct=True, order=0)
        Choice.objects.create(question=question, text='B', is_correct=False, order=1)
    return quiz


@override_settings(ALLOWED_HOSTS=['testserver'], EMAIL_NOTIFICATIONS_ENABLED=False)
class Phase1Base(TestCase):
    def setUp(self):
        self.teacher = make_user('prof_a', 'teacher')
        self.other_teacher = make_user('prof_b', 'teacher')
        self.student = make_user('eleve_a', 'student')
        self.outsider = make_user('eleve_b', 'student')
        course = Course.objects.create(name='Mathématiques', niveau='tronc_commun', order=1)
        self.lesson = Lesson.objects.create(course=course, order=1, title='Logique', content='x')
        self.classroom = Classroom.objects.create(
            name='TC1', niveau='tronc_commun', teacher=self.teacher,
        )
        self.classroom.add_member(self.student)
        other_class = Classroom.objects.create(
            name='TC2', niveau='tronc_commun', teacher=self.other_teacher,
        )
        other_class.add_member(self.outsider)
        self.quiz = make_quiz(self.teacher, self.lesson, 'Quiz A')
        self.other_quiz = make_quiz(self.other_teacher, self.lesson, 'Quiz B')

    def login_as(self, user):
        session = self.client.session
        session['user_id'] = user.pk
        session['password_session_version'] = user.password_session_version
        session.save()


class EditQuestionsValidationTests(Phase1Base):
    def test_invalid_input_shows_error_instead_of_server_error(self):
        self.login_as(self.teacher)
        question = self.quiz.questions.first()
        response = self.client.post(
            reverse('quizzes:edit_questions', args=[self.quiz.pk]),
            {'action': 'save', 'quiz_title': 'Quiz A', f'q_{question.pk}_text': ''},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'l’énoncé est obligatoire')


class AssignmentAuthorizationTests(Phase1Base):
    def test_teacher_cannot_assign_another_teachers_quiz(self):
        self.login_as(self.teacher)
        response = self.client.post(reverse('quizzes:assign'), {
            'quiz': self.other_quiz.pk, 'target': 'students', 'students': [self.student.pk],
        })
        self.assertEqual(response.status_code, 404)
        self.other_quiz.refresh_from_db()
        self.assertEqual(self.other_quiz.status, 'draft')
        self.assertFalse(QuizAssignment.objects.filter(quiz=self.other_quiz).exists())

    def test_teacher_cannot_assign_student_outside_their_classes(self):
        self.login_as(self.teacher)
        self.client.post(reverse('quizzes:assign'), {
            'quiz': self.quiz.pk, 'target': 'students',
            'students': [self.student.pk, self.outsider.pk],
        })
        assigned = set(QuizAssignment.objects.filter(quiz=self.quiz).values_list('student_id', flat=True))
        self.assertEqual(assigned, {self.student.pk})

    def test_assign_page_lists_only_managed_students_and_own_quizzes(self):
        self.login_as(self.teacher)
        response = self.client.get(reverse('quizzes:assign'))
        self.assertEqual(list(response.context['students']), [self.student])
        self.assertEqual(list(response.context['quizzes']), [self.quiz])

    def test_assignment_creates_a_single_notification(self):
        self.login_as(self.teacher)
        self.client.post(reverse('quizzes:assign'), {
            'quiz': self.quiz.pk, 'target': 'classroom', 'classroom': self.classroom.pk,
        })
        self.assertEqual(
            Notification.objects.filter(recipient=self.student, type='quiz_assigned').count(), 1,
        )


class CommentAuthorizationTests(Phase1Base):
    def test_teacher_cannot_comment_unrelated_attempt(self):
        attempt = Attempt.objects.create(
            student=self.outsider, quiz=self.other_quiz, submitted_at=timezone.now(), score=50,
        )
        self.login_as(self.teacher)
        response = self.client.post(
            reverse('quizzes:comment', args=[attempt.pk]), {'comment': 'intrusion'},
        )
        self.assertEqual(response.status_code, 404)
        attempt.refresh_from_db()
        self.assertEqual(attempt.teacher_comment, '')

    def test_teacher_can_comment_own_student_attempt(self):
        attempt = Attempt.objects.create(
            student=self.student, quiz=self.other_quiz, submitted_at=timezone.now(), score=50,
        )
        self.login_as(self.teacher)
        self.client.post(reverse('quizzes:comment', args=[attempt.pk]), {'comment': 'Bien'})
        attempt.refresh_from_db()
        self.assertEqual(attempt.teacher_comment, 'Bien')


class StateChangingActionsRequirePostTests(Phase1Base):
    def test_publish_and_duplicate_reject_get(self):
        self.login_as(self.teacher)
        self.assertEqual(self.client.get(reverse('quizzes:publish', args=[self.quiz.pk])).status_code, 405)
        self.assertEqual(self.client.get(reverse('quizzes:duplicate', args=[self.quiz.pk])).status_code, 405)
        self.quiz.refresh_from_db()
        self.assertEqual(self.quiz.status, 'draft')
        self.assertEqual(Quiz.objects.filter(created_by=self.teacher).count(), 1)

    def test_duplicate_keeps_points_and_difficulty(self):
        self.login_as(self.teacher)
        self.client.post(reverse('quizzes:duplicate', args=[self.quiz.pk]))
        copy = Quiz.objects.exclude(pk=self.quiz.pk).get(created_by=self.teacher)
        question = copy.questions.first()
        self.assertEqual(question.points, Decimal('2.00'))
        self.assertEqual(question.difficulty, 'difficile')

    def test_manage_counts_are_not_multiplied(self):
        Attempt.objects.create(student=self.student, quiz=self.quiz)
        Attempt.objects.create(student=self.student, quiz=self.quiz)
        self.login_as(self.teacher)
        response = self.client.get(reverse('quizzes:manage'))
        row = next(q for q in response.context['quizzes'] if q.pk == self.quiz.pk)
        self.assertEqual(row.nb_questions, 2)
        self.assertEqual(row.nb_attempts, 2)


class TakeQuizTests(Phase1Base):
    def setUp(self):
        super().setUp()
        self.quiz.status = 'published'
        self.quiz.save(update_fields=['status'])
        QuizAssignment.objects.create(quiz=self.quiz, student=self.student)
        self.attempt = Attempt.objects.create(student=self.student, quiz=self.quiz)
        self.login_as(self.student)
        self.take_url = reverse('quizzes:take', args=[self.attempt.pk])

    def _expire_current_question(self, question):
        self.client.get(self.take_url)
        session = self.client.session
        session[f'qstart_{self.attempt.pk}_{question.pk}'] = (
            timezone.now() - timedelta(seconds=120)
        ).isoformat()
        session.save()

    def test_late_answer_is_not_scored(self):
        first = self.quiz.get_questions().first()
        self._expire_current_question(first)
        self.client.post(self.take_url, {'answer': 'A'})
        answer = StudentAnswer.objects.get(attempt=self.attempt, question=first)
        self.assertFalse(answer.is_correct)
        self.assertEqual(answer.answer, '')

    def test_answer_in_time_is_scored(self):
        first = self.quiz.get_questions().first()
        self.client.get(self.take_url)
        self.client.post(self.take_url, {'answer': 'A'})
        self.assertTrue(StudentAnswer.objects.get(attempt=self.attempt, question=first).is_correct)

    def _finish_quiz(self):
        for _ in range(self.quiz.questions.count()):
            self.client.get(self.take_url)
            self.client.post(self.take_url, {'answer': 'A'})
        self.attempt.refresh_from_db()

    def test_finishing_sends_one_result_notification_per_recipient(self):
        self._finish_quiz()
        self.assertIsNotNone(self.attempt.submitted_at)
        self.assertEqual(self.attempt.score, 100.0)
        self.assertEqual(
            Notification.objects.filter(recipient=self.student, type='quiz_result').count(), 1,
        )
        self.assertEqual(
            Notification.objects.filter(recipient=self.teacher, type='quiz_result').count(), 1,
        )

    def test_viewing_results_has_no_side_effect(self):
        self._finish_quiz()
        results_url = reverse('quizzes:results', args=[self.attempt.pk])
        first = self.client.get(results_url)
        self.assertTrue(first.context['new_badges'])
        for _ in range(3):
            response = self.client.get(results_url)
            self.assertEqual(response.context['new_badges'], [])
        activity = DailyActivity.objects.get(user=self.student, day=timezone.localdate())
        self.assertEqual(activity.quiz_count, 1)
