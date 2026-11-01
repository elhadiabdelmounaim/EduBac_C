import json
import uuid
from decimal import Decimal
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from classrooms.models import Classroom, ClassroomMember
from education.models import Course, Lesson
from .models import Attempt, Choice, Quiz, QuizAssignment, QuizGenerationRun, Question


def question(question_id, statement, choices, answer, difficulty, points, **extra):
    return {
        'id': question_id,
        'type': 'multiple_choice',
        'statement': statement,
        'choices': [{'id': key, 'text': text} for key, text in choices],
        'correct_answer': answer,
        'difficulty': difficulty,
        'points': points,
        **extra,
    }


@override_settings(ALLOWED_HOSTS=['testserver'])
class QuizJsonImportTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(
            username='json-teacher', email='json-teacher@example.test', role='teacher',
        )
        self.student = User.objects.create_user(
            username='json-student', email='json-student@example.test', role='student',
        )
        self.outsider = User.objects.create_user(
            username='json-outsider', email='json-outsider@example.test', role='student',
        )
        self.course = Course.objects.create(name='Mathématiques', niveau='tronc_commun')
        self.lesson = Lesson.objects.create(
            course=self.course, title='Les nombres réels', order=1,
            content='Cours de mathématiques.',
        )
        self.classroom = Classroom.objects.create(
            name='TC A', niveau='tronc_commun', teacher=self.teacher,
        )
        ClassroomMember.objects.create(classroom=self.classroom, user=self.student)
        self.other_class = Classroom.objects.create(
            name='TC B', niveau='tronc_commun', teacher=self.teacher,
        )
        ClassroomMember.objects.create(classroom=self.other_class, user=self.outsider)
        self.document = {
            'quiz': {
                'title': 'Quiz importé',
                'level': 'TCS',
                'lesson': 'Les nombres réels',
                'duration': 20,
                'questions': [
                    question(
                        'Q001', 'Calculer $2+3$.',
                        [('A', '5'), ('B', '4'), ('C', '6'), ('D', '7')],
                        'A', 'easy', 1.5, explanation=r'$2+3=5$.',
                    ),
                    question(
                        'Q002', 'Calculer $2^2$.',
                        [('A', '1'), ('B', '2'), ('C', '4'), ('D', '9')],
                        'C', 'hard', 2.5,
                    ),
                ],
            },
        }
        self.url = reverse('quizzes:teacher_ai')
        self.generation_id = uuid.uuid4()
        self.login(self.teacher)

    def login(self, user):
        session = self.client.session
        session['user_id'] = user.pk
        session.save()

    def post_json(
        self, document=None, *, filename='quiz.json', generation_id=None,
        seconds_per_question=20, selected_lesson=None,
    ):
        selected_lesson = selected_lesson or self.lesson
        content = json.dumps(
            self.document if document is None else document, ensure_ascii=False,
        ).encode('utf-8')
        return self.client.post(self.url, {
            'action': 'import_json',
            'niveau': selected_lesson.course.niveau,
            'course': selected_lesson.course_id,
            'lesson': selected_lesson.pk,
            'seconds_per_question': seconds_per_question,
            'generation_id': str(generation_id or uuid.uuid4()),
            'quiz_json': SimpleUploadedFile(filename, content, content_type='application/json'),
        })

    @patch('ai.services.AIService.generate_quiz_from_lesson')
    def test_valid_json_creates_editable_draft_and_never_calls_ai(self, generate):
        response = self.post_json()

        self.assertRedirects(response, f'{self.url}?quiz=1', fetch_redirect_response=False)
        quiz = Quiz.objects.get()
        self.assertEqual(quiz.title, 'Quiz importé')
        self.assertEqual(quiz.lesson, self.lesson)
        self.assertEqual(quiz.duration, 1)
        self.assertEqual(quiz.seconds_per_question, 20)
        self.assertEqual(quiz.question_count, 2)
        self.assertEqual(quiz.difficulty, 'facile')
        self.assertEqual(quiz.status, 'draft')
        self.assertEqual(quiz.created_by, self.teacher)
        first, second = quiz.get_questions()
        self.assertEqual(first.text, 'Calculer $2+3$.')
        self.assertEqual(first.correct_answer, '5')
        self.assertEqual(first.explanation, r'$2+3=5$.')
        self.assertEqual(first.points, Decimal('1.50'))
        self.assertEqual(first.difficulty, 'facile')
        self.assertEqual(
            list(first.choices.order_by('order').values_list('text', 'is_correct')),
            [('5', True), ('4', False), ('6', False), ('7', False)],
        )
        self.assertEqual(second.points, Decimal('2.50'))
        self.assertEqual(second.difficulty, 'difficile')
        self.assertTrue(QuizGenerationRun.objects.filter(pk=response['X-Quiz-Generation-ID']).exists())
        generate.assert_not_called()

    @patch('ai.services.AIService.generate_quiz_from_lesson')
    def test_form_selection_sets_question_time_without_total_duration(self, generate):
        document = json.loads(json.dumps(self.document))
        document['quiz'].pop('level')
        document['quiz'].pop('lesson')

        response = self.post_json(document, seconds_per_question=45)

        self.assertEqual(response.status_code, 302)
        quiz = Quiz.objects.get()
        self.assertEqual(quiz.lesson, self.lesson)
        self.assertEqual(quiz.seconds_per_question, 45)
        self.assertEqual(quiz.duration, 2)
        generate.assert_not_called()

    def test_invalid_question_time_is_rejected_without_creating_a_quiz(self):
        response = self.post_json(seconds_per_question='601')

        self.assertContains(response, 'entre 5 et 600 secondes')
        self.assertFalse(Quiz.objects.exists())

    @patch('ai.services.AIService.generate_quiz_from_lesson')
    def test_old_internal_generation_action_is_disabled(self, generate):
        response = self.client.post(self.url, {
            'action': 'generate',
            'niveau': 'tronc_commun',
            'lesson': self.lesson.pk,
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'génération interne est désactivée')
        self.assertFalse(Quiz.objects.exists())
        generate.assert_not_called()

    def test_invalid_json_does_not_create_any_records(self):
        invalid = json.loads(json.dumps(self.document))
        invalid['quiz']['questions'][0]['correct_answer'] = 'Z'
        response = self.post_json(invalid)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'ne correspond à aucun identifiant')
        self.assertFalse(Quiz.objects.exists())
        self.assertFalse(Question.objects.exists())
        self.assertFalse(Choice.objects.exists())

    def test_rejects_wrong_extension_unknown_lesson_and_duplicate_json_keys(self):
        response = self.post_json(filename='quiz.txt')
        self.assertContains(response, 'extension .json')
        self.assertFalse(Quiz.objects.exists())

        invalid = json.loads(json.dumps(self.document))
        invalid['quiz']['lesson'] = 'Leçon inconnue'
        response = self.post_json(invalid)
        self.assertContains(response, 'ne correspond pas à celle choisie')
        self.assertFalse(Quiz.objects.exists())

        duplicate = (
            b'{"quiz":{"title":"First","title":"Second","level":"TCS",'
            b'"lesson":"Les nombres r\xc3\xa9els","duration":5,"questions":[]}}'
        )
        response = self.client.post(self.url, {
            'action': 'import_json',
            'niveau': self.course.niveau,
            'course': self.course.pk,
            'lesson': self.lesson.pk,
            'seconds_per_question': '20',
            'generation_id': str(uuid.uuid4()),
            'quiz_json': SimpleUploadedFile('duplicate.json', duplicate),
        })
        self.assertContains(response, 'clé répétée')
        self.assertFalse(Quiz.objects.exists())

    def test_duplicate_post_with_the_same_request_id_does_not_duplicate_the_quiz(self):
        identifier = uuid.uuid4()
        self.post_json(generation_id=identifier)
        response = self.post_json(generation_id=identifier)
        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        self.assertEqual(Quiz.objects.count(), 1)
        self.assertContains(self.client.get(self.url), 'déjà été reçu')

    @patch('ai.services.AIService.generate_quiz_from_lesson')
    def test_teacher_can_edit_question_time_points_difficulty_and_questions(self, generate):
        self.post_json()
        quiz = Quiz.objects.get()
        first, _second = quiz.get_questions()
        correct_choice = first.choices.get(is_correct=True)
        incorrect_choice = first.choices.filter(is_correct=False).first()
        response = self.client.post(reverse('quizzes:edit_questions', args=[quiz.pk]), {
            'action': 'save',
            'quiz_title': 'Quiz révisé',
            'seconds_per_question': '45',
            f'q_{first.pk}_text': 'Calculer $3+3$.',
            f'q_{first.pk}_correct': '6',
            f'q_{first.pk}_expl': 'On additionne les deux termes.',
            f'q_{first.pk}_difficulty': 'moyen',
            f'q_{first.pk}_points': '3',
            f'c_{correct_choice.pk}_text': '6',
            f'c_{correct_choice.pk}_ok': 'on',
            f'c_{incorrect_choice.pk}_text': incorrect_choice.text,
            f'c_{first.choices.filter(is_correct=False).order_by("order")[1].pk}_text': 'Autre réponse',
            f'c_{first.choices.filter(is_correct=False).order_by("order")[2].pk}_text': 'Encore une réponse',
        })

        self.assertRedirects(response, f'{self.url}?quiz={quiz.pk}', fetch_redirect_response=False)
        quiz.refresh_from_db()
        first.refresh_from_db()
        correct_choice.refresh_from_db()
        self.assertEqual(quiz.title, 'Quiz révisé')
        self.assertEqual(quiz.duration, 2)
        self.assertEqual(quiz.seconds_per_question, 45)
        self.assertEqual(quiz.question_count, 2)
        self.assertEqual(first.text, 'Calculer $3+3$.')
        self.assertEqual(first.points, Decimal('3.00'))
        self.assertEqual(first.difficulty, 'moyen')
        self.assertEqual(correct_choice.text, '6')
        generate.assert_not_called()

    @patch('ai.services.AIService.generate_quiz_from_lesson')
    def test_class_assignment_is_limited_to_members_and_student_score_uses_points(self, generate):
        self.post_json()
        quiz = Quiz.objects.get()
        response = self.client.post(self.url, {
            'action': 'send',
            'quiz_id': quiz.pk,
            'classroom': self.classroom.pk,
        })
        self.assertRedirects(response, reverse('quizzes:manage'), fetch_redirect_response=False)
        quiz.refresh_from_db()
        self.assertEqual(quiz.status, 'published')
        self.assertEqual(quiz.classroom, self.classroom)
        self.assertQuerySetEqual(
            QuizAssignment.objects.filter(quiz=quiz).order_by('student_id').values_list('student_id', flat=True),
            [self.student.pk],
        )

        self.login(self.student)
        self.assertEqual(self.client.get(reverse('quizzes:detail', args=[quiz.pk])).status_code, 200)
        start = self.client.get(reverse('quizzes:start', args=[quiz.pk]))
        self.assertEqual(start.status_code, 302)
        attempt = Attempt.objects.get(student=self.student, quiz=quiz)
        first, second = quiz.get_questions()
        self.client.post(reverse('quizzes:take', args=[attempt.pk]), {
            'answer': first.choices.get(is_correct=True).text,
        })
        final = self.client.post(reverse('quizzes:take', args=[attempt.pk]), {
            'answer': second.choices.filter(is_correct=False).first().text,
        })
        self.assertEqual(final.status_code, 302)
        attempt.refresh_from_db()
        self.assertEqual(attempt.score, 37.5)
        generate.assert_not_called()

        self.login(self.outsider)
        self.assertNotEqual(
            self.client.get(reverse('quizzes:detail', args=[quiz.pk])).status_code, 200,
        )
