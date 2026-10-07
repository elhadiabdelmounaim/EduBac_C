from pathlib import Path
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from education.models import Course, Lesson
from quizzes.math_text import latex_to_plain, normalize_math_text
from quizzes.models import Choice, Question, Quiz


@override_settings(ALLOWED_HOSTS=['testserver', 'localhost', '127.0.0.1'])
class QuizLessonSelectionTests(TestCase):
    def setUp(self):
        self.teacher = User(username='quiz_teacher', email='quiz-teacher@test.com', role='teacher')
        self.teacher.set_password('pass123')
        self.teacher.save()

        self.course = Course.objects.create(
            name='Mathématiques',
            niveau='tronc_commun',
            order=1,
        )
        self.lesson = Lesson.objects.create(
            course=self.course,
            order=1,
            title='Les nombres réels',
            content='Contenu du cours',
        )
        self.other_lesson = Lesson.objects.create(
            course=self.course,
            order=2,
            title='Les polynômes',
            content='Contenu du cours',
        )
        Quiz.objects.create(
            title='Quiz nombres réels',
            lesson=self.lesson,
            created_by=self.teacher,
        )
        Quiz.objects.create(
            title='Quiz polynômes',
            lesson=self.other_lesson,
            created_by=self.teacher,
        )

        self.client.post('/compte/connexion/', {
            'username': self.teacher.username,
            'password': 'pass123',
        })

    def test_my_quizzes_filters_by_selected_lesson(self):
        response = self.client.get(
            reverse('quizzes:manage'),
            {'lesson': self.lesson.pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Choisir une leçon')
        self.assertContains(response, 'Quiz nombres réels')
        self.assertNotContains(response, 'Quiz polynômes')
        self.assertContains(response, f'?lesson={self.lesson.pk}')

    def test_my_quizzes_lessons_depend_on_the_selected_level(self):
        initial_response = self.client.get(reverse('quizzes:manage'))
        self.assertEqual(initial_response.status_code, 200)
        self.assertFalse(initial_response.context['lessons'].exists())

        response = self.client.get(
            reverse('quizzes:manage'),
            {'niveau': self.course.niveau},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            list(response.context['lessons'].values_list('pk', flat=True)),
            [self.lesson.pk, self.other_lesson.pk],
        )
        self.assertContains(response, f'data-niveau="{self.course.niveau}"')
        self.assertContains(response, 'name="niveau"')

    def test_selected_lesson_opens_preselected_in_quiz_generator(self):
        response = self.client.get(
            reverse('quizzes:teacher_ai'),
            {'lesson': self.lesson.pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['selected_niveau'], self.course.niveau)
        self.assertEqual(response.context['selected_lesson_id'], str(self.lesson.pk))
        self.assertRegex(
            response.content.decode(),
            rf'<option value="{self.lesson.pk}" data-niveau="{self.course.niveau}"[^>]*selected',
        )

    def test_generator_form_has_optional_description_textarea(self):
        response = self.client.get(reverse('quizzes:teacher_ai'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<label for="quizDescription" class="mb-0">Description du quiz</label>', html=True)
        self.assertContains(
            response,
            'Décrivez les notions, compétences ou types de questions sur lesquels le quiz doit se concentrer...',
        )
        rendered_form = response.content.decode()
        self.assertRegex(rendered_form, r'<textarea[^>]*name="description"[^>]*rows="5"')
        self.assertNotRegex(rendered_form, r'<textarea[^>]*name="description"[^>]*required')
        self.assertContains(response, 'Generating quiz...')
        self.assertNotContains(response, 'data-loading')

    @patch('ai.services.AIService.generate_quiz_from_lesson')
    def test_generator_shows_a_clear_failure_without_saving_a_quiz(self, generate_quiz):
        from ai.providers import AIProviderError
        generate_quiz.side_effect = AIProviderError(
            'Rate limit Groq', code='rate_limit', retry_after=20,
        )

        before = Quiz.objects.count()
        response = self.client.post(reverse('quizzes:teacher_ai'), {
            'action': 'generate',
            'niveau': self.course.niveau,
            'lesson': self.lesson.pk,
            'question_count': 1,
            'seconds_per_question': 20,
            'difficulty': 'moyen',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Generation failed:')
        self.assertContains(response, 'IA atteinte')
        self.assertContains(response, '20 secondes')
        self.assertEqual(Quiz.objects.count(), before)

    @patch('ai.services.AIService.generate_quiz_from_lesson')
    def test_teacher_generator_stores_latex_fields_without_plain_text_conversion(
        self, generate_quiz,
    ):
        question_text = r'Calculer $\frac{1}{2}$.'
        choice_text = r'$\frac{1}{2}$'
        explanation = r'$\frac{1}{2} = 0.5$'
        hint = r'Réduis $\frac{2}{4}$.'
        generate_quiz.return_value = {
            'title': 'Quiz LaTeX',
            'questions': [{
                'text': question_text,
                'correct_answer': choice_text,
                'explanation': explanation,
                'hint': hint,
                'choices': [
                    {'text': choice_text, 'is_correct': True},
                    {'text': '1', 'is_correct': False},
                    {'text': '2', 'is_correct': False},
                    {'text': '4', 'is_correct': False},
                ],
            }],
        }

        response = self.client.post(reverse('quizzes:teacher_ai'), {
            'action': 'generate',
            'niveau': self.course.niveau,
            'lesson': self.lesson.pk,
            'question_count': 1,
            'seconds_per_question': 20,
            'difficulty': 'moyen',
        })

        self.assertEqual(response.status_code, 200)
        quiz = Quiz.objects.get(title='Quiz LaTeX')
        self.assertEqual(quiz.description, '')
        question = Question.objects.get(quiz=quiz)
        self.assertEqual(question.text, question_text)
        self.assertEqual(question.correct_answer, choice_text)
        self.assertEqual(question.explanation, explanation)
        self.assertEqual(question.hint, hint)
        self.assertEqual(
            question.choices.order_by('order').first().text,
            choice_text,
        )
        self.assertContains(response, r'\frac')

    @patch('ai.services.AIService.generate_quiz_from_lesson')
    def test_teacher_generator_saves_and_forwards_description(self, generate_quiz):
        generate_quiz.return_value = {
            'title': 'Quiz ciblé',
            'questions': [{
                'text': 'Calculer 2 + 2',
                'correct_answer': '4',
                'explanation': 'Addition directe.',
                'hint': 'Additionne les deux termes.',
                'choices': [
                    {'text': '4', 'is_correct': True},
                    {'text': '3', 'is_correct': False},
                ],
            }],
        }
        description = 'Prioriser les additions avec plusieurs étapes.'

        response = self.client.post(reverse('quizzes:teacher_ai'), {
            'action': 'generate',
            'niveau': self.course.niveau,
            'lesson': self.lesson.pk,
            'question_count': 1,
            'seconds_per_question': 20,
            'difficulty': 'moyen',
            'description': description,
        })

        self.assertEqual(response.status_code, 200)
        quiz = Quiz.objects.get(title='Quiz ciblé')
        self.assertEqual(quiz.description, description)
        self.assertEqual(response.context['quiz_description'], description)
        self.assertContains(response, description)
        generate_quiz.assert_called_once_with(
            self.lesson,
            1,
            'moyen',
            provider=None,
            model=None,
            description=description,
        )


class MathTextNormalizationTests(TestCase):
    def test_normalizer_preserves_latex_and_converts_supported_delimiters(self):
        text = r'  \(\frac{1}{2}\) et \[\sqrt{x}\]  '

        self.assertEqual(
            normalize_math_text(text),
            r'$\frac{1}{2}$ et $$\sqrt{x}$$',
        )

    def test_normalizer_escapes_unmatched_dollars_without_changing_plain_text(self):
        self.assertEqual(normalize_math_text('  Texte simple  '), 'Texte simple')
        self.assertEqual(normalize_math_text('Prix $5'), r'Prix \$5')
        self.assertEqual(normalize_math_text(r'Coût \$5'), r'Coût \$5')

    def test_latex_to_plain_remains_available_for_non_html_exports(self):
        self.assertEqual(latex_to_plain('Texte simple'), 'Texte simple')


class LocalKaTeXAssetTests(TestCase):
    def test_math_pages_use_local_pinned_assets_only(self):
        project_root = Path(__file__).resolve().parent.parent
        template_root = project_root / 'templates'
        template_paths = [
            'quizzes/take.html',
            'quizzes/review.html',
            'quizzes/results.html',
            'quizzes/feedback.html',
            'quizzes/teacher_ai_quiz.html',
            'quizzes/question_stats.html',
            'quizzes/teacher_stats.html',
            'quizzes/error_analysis.html',
            'whiteboard/quiz_correction.html',
            'education/lesson_detail.html',
        ]

        for template_path in template_paths:
            with self.subTest(template=template_path):
                source = (template_root / template_path).read_text()
                self.assertIn('includes/katex.html', source)
                self.assertNotIn('cdn.jsdelivr.net/npm/katex', source)

        include = (template_root / 'includes/katex.html').read_text()
        self.assertIn("vendor/katex/katex.min.css", include)
        self.assertIn("vendor/katex/katex.min.js", include)
        self.assertIn("vendor/katex/contrib/auto-render.min.js", include)
        self.assertIn('window.renderMath = function', include)
        self.assertNotIn('cdn.jsdelivr.net/npm/katex', include)

        asset_root = project_root / 'static' / 'vendor' / 'katex'
        self.assertTrue((asset_root / 'katex.min.css').is_file())
        self.assertTrue((asset_root / 'katex.min.js').is_file())
        self.assertTrue((asset_root / 'contrib' / 'auto-render.min.js').is_file())
        self.assertTrue(any((asset_root / 'fonts').glob('*.woff2')))
