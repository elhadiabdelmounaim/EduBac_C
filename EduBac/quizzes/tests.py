from pathlib import Path
import json
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import NoReverseMatch, Resolver404, resolve, reverse

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

    def test_quiz_creation_page_uses_external_json_instead_of_internal_generation(self):
        response = self.client.get(
            reverse('quizzes:teacher_ai'),
            {'lesson': self.lesson.pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Importer un quiz')
        self.assertContains(response, 'name="quiz_json"')
        self.assertContains(response, 'accept=".json,application/json"')
        self.assertNotContains(response, 'aiProviderSelect')
        self.assertNotContains(response, 'Générer le quiz avec l’IA')

    def test_teacher_creation_page_explains_the_external_json_format(self):
        response = self.client.get(reverse('quizzes:teacher_ai'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'multiple_choice')
        self.assertContains(response, 'correct_answer')
        self.assertContains(response, 'points')
        self.assertContains(response, 'n’appelle pas de service d’intelligence artificielle')

    @patch('ai.services.AIService.generate_quiz_from_lesson')
    def test_legacy_internal_generation_action_is_rejected_without_calling_ai(self, generate_quiz):
        response = self.client.post(reverse('quizzes:teacher_ai'), {
            'action': 'generate',
            'niveau': self.course.niveau,
            'lesson': self.lesson.pk,
            'question_count': 1,
            'seconds_per_question': 20,
            'difficulty': 'moyen',
            'description': 'Évaluer les opérations sur les nombres réels.',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'génération interne est désactivée')
        self.assertEqual(Quiz.objects.count(), 2)
        generate_quiz.assert_not_called()

    @patch('ai.services.AIService.generate_quiz_from_lesson')
    def test_json_import_stores_latex_and_optional_description_without_ai(self, generate_quiz):
        question_text = r'Calculer $\frac{1}{2}$.'
        choice_text = r'$\frac{1}{2}$'
        explanation = r'$\frac{1}{2} = 0.5$'
        hint = r'Réduis $\frac{2}{4}$.'
        document = {
            'quiz': {
                'title': 'Quiz LaTeX',
                'description': 'Calculs sur les fractions.',
                'level': 'tronc_commun',
                'lesson': self.lesson.title,
                'duration': 15,
                'questions': [{
                    'id': 'Q-LATEX',
                    'type': 'multiple_choice',
                    'statement': question_text,
                    'correct_answer': 'A',
                    'difficulty': 'medium',
                    'points': 1,
                    'explanation': explanation,
                    'hint': hint,
                    'choices': [
                        {'id': 'A', 'text': choice_text},
                        {'id': 'B', 'text': '1'},
                        {'id': 'C', 'text': '2'},
                        {'id': 'D', 'text': '4'},
                    ],
                }],
            },
        }
        response = self.client.post(reverse('quizzes:teacher_ai'), {
            'action': 'import_json',
            'quiz_json': SimpleUploadedFile(
                'latex.json', json.dumps(document, ensure_ascii=False).encode(),
                content_type='application/json',
            ),
        })

        self.assertEqual(response.status_code, 302)
        quiz = Quiz.objects.get(title='Quiz LaTeX')
        self.assertEqual(quiz.description, 'Calculs sur les fractions.')
        question = Question.objects.get(quiz=quiz)
        self.assertEqual(question.text, question_text)
        self.assertEqual(question.correct_answer, choice_text)
        self.assertEqual(question.explanation, explanation)
        self.assertEqual(question.hint, hint)
        self.assertEqual(
            question.choices.order_by('order').first().text,
            choice_text,
        )
        self.assertEqual(quiz.duration, 15)
        generate_quiz.assert_not_called()


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


class RemovedWeakPointsFeatureTests(TestCase):
    def test_former_analysis_page_is_not_routable(self):
        with self.assertRaises(Resolver404):
            resolve('/quizzes/analyse-erreurs/')
        with self.assertRaises(NoReverseMatch):
            reverse('quizzes:errors')

    def test_templates_do_not_offer_removed_feature(self):
        template_root = Path(__file__).resolve().parent.parent / 'templates'
        for path in template_root.rglob('*.html'):
            source = path.read_text(encoding='utf-8')
            with self.subTest(template=str(path.relative_to(template_root))):
                for removed in ('quizzes:errors', 'Mes points faibles', 'Mes erreurs', 'Points faibles'):
                    self.assertNotIn(removed, source)
        self.assertNotIn(
            "Besoin d'une explication ?",
            (template_root / 'education/lesson_detail.html').read_text(encoding='utf-8'),
        )


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
