from io import BytesIO

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from accounts.models import User
from classrooms.models import Classroom, ClassroomMember
from education.models import Course, Lesson
from quizzes.models import Quiz, Attempt


class ExcelExportTests(TestCase):
    def test_class_export_has_only_four_columns_and_filters_members(self):
        teacher = User.objects.create_user(username='export-teacher', email='teacher@example.test', role='teacher')
        other = User.objects.create_user(username='other-teacher', email='other@example.test', role='teacher')
        student = User.objects.create_user(username='export-student', role='student',
                                           email='student@example.test', first_name='Amine', last_name='=Nom')
        outsider = User.objects.create_user(username='other-student', email='outsider@example.test', role='student')
        classroom = Classroom.objects.create(name='Classe A', teacher=teacher, niveau='tronc_commun')
        foreign = Classroom.objects.create(name='Classe B', teacher=other, niveau='tronc_commun')
        ClassroomMember.objects.create(classroom=classroom, user=student)
        course = Course.objects.create(name='Maths', niveau='tronc_commun')
        lesson = Lesson.objects.create(course=course, title='Algèbre')
        quiz = Quiz.objects.create(title='Quiz algèbre', lesson=lesson, created_by=teacher)
        Attempt.objects.create(student=student, quiz=quiz, score=75, submitted_at=timezone.now())
        Attempt.objects.create(student=outsider, quiz=quiz, score=90, submitted_at=timezone.now())
        Attempt.objects.create(student=student, quiz=quiz)  # unfinished: not exported
        self.client.force_login(teacher)
        session = self.client.session
        session['user_id'] = teacher.pk
        session.save()
        response = self.client.get(reverse('quizzes:export_excel'), {'classe': classroom.pk})
        self.assertEqual(response.status_code, 200)
        sheet = load_workbook(BytesIO(response.content)).active
        self.assertEqual(list(sheet.values), [
            ('Nom', 'Prénom', 'Quiz', 'Note (%)'),
            ('=Nom', 'Amine', 'Quiz algèbre', 75),
        ])
        self.assertEqual(sheet['A2'].data_type, 's')
        self.assertEqual(self.client.get(reverse('quizzes:export_excel'),
                                        {'classe': foreign.pk}).status_code, 404)
        page = self.client.get(reverse('quizzes:student_results'), {'classe': classroom.pk})
        self.assertContains(page, 'Exporter cette classe en Excel')
        self.assertContains(page, f'?classe={classroom.pk}')
