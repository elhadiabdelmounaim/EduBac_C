from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from accounts.models import User
from chat.models import PrivateConversation
from classrooms.models import Classroom
from education.models import Course, Lesson
from quizzes.models import Quiz


class ConsolidateTeacherCommandTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create(
            username='admin', email='admin@example.test', is_staff=True, is_superuser=True,
        )
        self.old = User.objects.create(username='ancien-prof', email='old@example.test', role='teacher')
        self.student = User.objects.create(username='eleve', email='eleve@example.test')
        self.classroom = Classroom.objects.create(name='1BAC', niveau='tronc_commun', teacher=self.old)
        course = Course.objects.create(name='Maths', niveau='tronc_commun', order=1)
        lesson = Lesson.objects.create(course=course, order=1, title='Ensembles', content='…')
        self.quiz = Quiz.objects.create(title='Q1', lesson=lesson, created_by=self.old)
        PrivateConversation.objects.create(classroom=self.classroom, student=self.student, teacher=self.old)

    def run_command(self, *args):
        out = StringIO()
        call_command('consolidate_teacher', *args, stdout=out)
        return out.getvalue()

    def test_simulation_changes_nothing(self):
        output = self.run_command()
        self.assertIn('Simulation', output)
        self.assertIn('classes : 1', output)
        self.classroom.refresh_from_db()
        self.old.refresh_from_db()
        self.assertEqual(self.classroom.teacher, self.old)
        self.assertTrue(self.old.is_active)

    def test_apply_moves_ownership_to_admin_and_deactivates_old_teacher(self):
        self.run_command('--apply')
        self.classroom.refresh_from_db()
        self.quiz.refresh_from_db()
        self.old.refresh_from_db()
        self.assertEqual(self.classroom.teacher, self.admin)
        self.assertEqual(self.quiz.created_by, self.admin)
        self.assertEqual(PrivateConversation.objects.get().teacher, self.admin)
        self.assertFalse(self.old.is_active)
        self.assertTrue(User.objects.filter(pk=self.old.pk).exists(), 'aucun compte supprimé')
        self.assertIn('rien à faire', self.run_command('--apply'))

    def test_existing_admin_consultation_is_not_duplicated(self):
        PrivateConversation.objects.create(classroom=self.classroom, student=self.student, teacher=self.admin)
        self.run_command('--apply')
        self.assertEqual(PrivateConversation.objects.filter(teacher=self.admin).count(), 1)
