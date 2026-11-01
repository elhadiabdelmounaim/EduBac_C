import json
import re
import shutil
from unittest.mock import patch

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from accounts.models import TeacherProfile, User
from classrooms.models import Classroom, ClassroomMember
from education.models import Course, Lesson
from quizzes.models import Attempt, Quiz, QuizAssignment


class QuizJsonImportBrowserTests(StaticLiveServerTestCase):
    def test_teacher_imports_edits_assigns_and_student_completes_quiz_without_ai(self):
        teacher = User.objects.create_user(
            username='json-browser-teacher', email='json-browser-teacher@example.test',
            password='Browser-test-only-123!', role='teacher',
        )
        TeacherProfile.objects.get_or_create(user=teacher)
        student = User.objects.create_user(
            username='json-browser-student', email='json-browser-student@example.test',
            password='Browser-test-only-123!', role='student',
        )
        outsider = User.objects.create_user(
            username='json-browser-outsider', email='json-browser-outsider@example.test',
            password='Browser-test-only-123!', role='student',
        )
        course = Course.objects.create(name='Mathématiques', niveau='tronc_commun')
        lesson = Lesson.objects.create(course=course, title='Calculs importés', order=1)
        classroom = Classroom.objects.create(
            name='Tronc commun A', niveau=course.niveau, teacher=teacher,
        )
        ClassroomMember.objects.create(classroom=classroom, user=student)
        other_class = Classroom.objects.create(
            name='Tronc commun B', niveau=course.niveau, teacher=teacher,
        )
        ClassroomMember.objects.create(classroom=other_class, user=outsider)
        document = {
            'quiz': {
                'title': 'Quiz JSON',
                'level': 'TCS',
                'lesson': lesson.title,
                'duration': 20,
                'questions': [
                    {
                        'id': 'Q001', 'type': 'multiple_choice',
                        'statement': 'Calculer $2+3$.', 'correct_answer': 'A',
                        'difficulty': 'easy', 'points': 1,
                        'choices': [
                            {'id': 'A', 'text': '5'}, {'id': 'B', 'text': '4'},
                            {'id': 'C', 'text': '6'}, {'id': 'D', 'text': '7'},
                        ],
                    },
                    {
                        'id': 'Q002', 'type': 'multiple_choice',
                        'statement': 'Calculer $2^2$.', 'correct_answer': 'C',
                        'difficulty': 'hard', 'points': 3,
                        'choices': [
                            {'id': 'A', 'text': '1'}, {'id': 'B', 'text': '2'},
                            {'id': 'C', 'text': '4'}, {'id': 'D', 'text': '9'},
                        ],
                    },
                ],
            },
        }
        base_url = self.live_server_url

        def log_in(page, email):
            page.goto(base_url + reverse('accounts:login'))
            page.locator('[name="email"]').fill(email)
            page.locator('[name="password"]').fill('Browser-test-only-123!')
            page.get_by_role('button', name='Se connecter', exact=True).click()
            page.wait_for_url(base_url + reverse('accounts:dashboard'))

        with patch(
            'ai.services.AIService.generate_quiz_from_lesson',
            side_effect=AssertionError('Le flux JSON ne doit pas appeler l’IA.'),
        ), sync_playwright() as pw:
            browser = pw.chromium.launch(
                executable_path=shutil.which('chromium'),
                headless=True,
                args=['--no-sandbox'],
            )
            try:
                teacher_context = browser.new_context(viewport={'width': 1280, 'height': 1000})
                teacher_page = teacher_context.new_page()
                log_in(teacher_page, teacher.email)
                teacher_page.goto(base_url + reverse('quizzes:teacher_ai'))
                expect(teacher_page.get_by_role('heading', name='Importer un quiz')).to_be_visible()
                teacher_page.locator('#quizLevel').select_option(course.niveau)
                teacher_page.locator('#quizCourse').select_option(str(course.pk))
                teacher_page.locator('#quizLesson').select_option(str(lesson.pk))
                teacher_page.locator('#secondsPerQuestion').fill('45')
                teacher_page.locator('#quizJsonFile').set_input_files({
                    'name': 'quiz.json',
                    'mimeType': 'application/json',
                    'buffer': json.dumps(document, ensure_ascii=False).encode('utf-8'),
                })
                teacher_page.get_by_role(
                    'button', name='Valider et créer le brouillon',
                ).click()
                teacher_page.wait_for_url(re.compile(
                    re.escape(base_url + reverse('quizzes:teacher_ai')) + r'\?quiz=\d+',
                ))
                expect(teacher_page.get_by_role('heading', name='Quiz JSON')).to_be_visible()
                expect(teacher_page.get_by_text('45 s/question')).to_be_visible()
                expect(teacher_page.locator('math').first).to_be_visible()
                expect(teacher_page.locator('math').first).to_contain_text('2')

                quiz_id = int(re.search(r'\?quiz=(\d+)$', teacher_page.url).group(1))
                teacher_page.get_by_role('link', name='Modifier le quiz').click()
                teacher_page.locator('#quizTitle').fill('Quiz JSON révisé')
                teacher_page.locator('#quizDuration').fill('30')
                teacher_page.locator('input[name$="_points"]').first.fill('2')
                teacher_page.locator('input[name$="_points"]').nth(1).fill('3')
                invalid_controls = teacher_page.locator('#editQuestionsForm').evaluate(
                    "form => Array.from(form.elements).filter(e => !e.checkValidity()).map(e => "
                    "({name: e.name, value: e.value, message: e.validationMessage}))",
                )
                self.assertEqual(invalid_controls, [])
                with teacher_page.expect_response(
                    lambda response: (
                        response.request.method == 'POST'
                        and reverse('quizzes:edit_questions', args=[quiz_id])
                        in response.request.url
                    ),
                ) as edit_response:
                    teacher_page.get_by_role('button', name='Enregistrer').click()
                if edit_response.value.status != 302:
                    self.fail(
                        'La sauvegarde a été refusée : '
                        + teacher_page.locator('.alert').all_text_contents().__str__()
                    )
                teacher_page.wait_for_url(re.compile(
                    re.escape(base_url + reverse('quizzes:teacher_ai')) + r'\?quiz=\d+',
                ))
                expect(teacher_page.get_by_text('30 min')).to_be_visible()
                expect(teacher_page.get_by_text('45 s/question')).to_be_visible()

                teacher_page.locator('#classroomSelect').select_option(str(classroom.pk))
                teacher_page.get_by_role('button', name='Publier et affecter').click()
                teacher_page.wait_for_url(base_url + reverse('quizzes:manage'))

                student_context = browser.new_context(viewport={'width': 1280, 'height': 1000})
                student_page = student_context.new_page()
                log_in(student_page, student.email)
                student_page.goto(base_url + reverse('quizzes:detail', args=[quiz_id]))
                expect(student_page.get_by_role('heading', name='Quiz JSON révisé')).to_be_visible()
                student_page.goto(base_url + reverse('quizzes:start', args=[quiz_id]))
                student_page.wait_for_url(re.compile(r'/quizzes/tentative/\d+/$'))
                student_page.locator('input[name="answer"]').nth(0).check()
                student_page.get_by_role('button', name='Question suivante').click()
                student_page.locator('input[name="answer"]').nth(0).check()
                student_page.get_by_role('button', name='Terminer le quiz').click()
                student_page.wait_for_url(re.compile(r'/quizzes/tentative/\d+/resultats/$'))

                outsider_context = browser.new_context()
                outsider_page = outsider_context.new_page()
                log_in(outsider_page, outsider.email)
                outsider_page.goto(base_url + reverse('quizzes:detail', args=[quiz_id]))
                self.assertIn(reverse('quizzes:assigned'), outsider_page.url)
                student_context.close()
                outsider_context.close()
                teacher_context.close()
            finally:
                browser.close()

        quiz = Quiz.objects.get(pk=quiz_id)
        self.assertEqual(Quiz.objects.count(), 1)
        self.assertEqual(quiz.seconds_per_question, 45)
        self.assertEqual(quiz.status, 'published')
        self.assertEqual(quiz.classroom_id, classroom.pk)
        self.assertQuerySetEqual(
            QuizAssignment.objects.filter(quiz=quiz).values_list('student_id', flat=True),
            [student.pk],
        )
        self.assertEqual(
            list(quiz.questions.order_by('order').values_list('points', flat=True)),
            [2, 3],
        )
        attempt = Attempt.objects.get(quiz=quiz, student=student)
        self.assertEqual(attempt.score, 40.0)
