from unittest.mock import patch
from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from education.models import Course, Lesson
from .models import AIConversation, AIMessage
from .providers import AIProviderError
from .prompts import build_quiz_prompt
from .services import AIService, repair_latex_escapes


@override_settings(ALLOWED_HOSTS=['testserver'])
class TutorTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='learner', email='learner@example.test')
        self.other = User.objects.create_user(username='other', email='other@example.test')
        course = Course.objects.create(name='Algèbre', niveau='tronc_commun')
        self.lesson = Lesson.objects.create(
            title='Équations', content='Pour résoudre x + 2 = 5, soustraire 2.', course=course,
        )
        session = self.client.session
        session['user_id'] = self.user.pk
        session.save()
        self.url = reverse('ai:assistant')

    def post(self, **extra):
        data = {'lesson_id': self.lesson.pk, 'question': 'Comment résoudre cette équation?'}
        data.update(extra)
        return self.client.post(self.url, data)

    @patch('ai.views.AIService.generate_explanation', return_value='Soustrais 2 aux deux membres.')
    def test_saved_followup_uses_history_and_refresh_does_not_resend(self, generate):
        response = self.post()
        self.assertEqual(response.status_code, 302)
        conversation = AIConversation.objects.get()
        page = self.client.get(response.url)
        self.assertContains(page, 'Comment résoudre cette équation?')
        self.assertContains(page, 'Soustrais 2 aux deux membres.')
        self.assertEqual(generate.call_count, 1)
        self.post(conversation_id=conversation.pk, question='Donc x = 3 ?', style='erreur')
        history = generate.call_args.kwargs['conversation_history']
        self.assertEqual([turn['role'] for turn in history], ['user', 'assistant'])
        self.assertEqual(AIConversation.objects.count(), 1)
        self.assertEqual(conversation.messages.count(), 4)

    @patch('ai.views.AIService.generate_explanation')
    def test_other_users_conversation_is_inaccessible_before_provider_call(self, generate):
        conversation = AIConversation.objects.create(user=self.other, lesson=self.lesson)
        self.assertEqual(self.post(conversation_id=conversation.pk).status_code, 404)
        self.assertEqual(self.client.get(self.url, {'c': conversation.pk}).status_code, 404)
        generate.assert_not_called()

    @patch('ai.views.AIService.generate_explanation')
    def test_conversation_cannot_switch_lessons(self, generate):
        conversation = AIConversation.objects.create(user=self.user, lesson=self.lesson)
        lesson = Lesson.objects.create(title='Autre', content='Autre', course=self.lesson.course)
        self.assertEqual(
            self.post(conversation_id=conversation.pk, lesson_id=lesson.pk).status_code, 404,
        )
        generate.assert_not_called()

    @patch('ai.views.AIService.generate_explanation')
    def test_invalid_questions_do_not_call_provider(self, generate):
        for question in (' ', 'x' * 4001):
            response = self.post(question=question)
            self.assertContains(response, '4 000 caractères')
        response = self.post(lesson_id='')
        self.assertContains(response, 'Choisis une leçon')
        generate.assert_not_called()
        self.assertEqual(AIConversation.objects.count(), 0)

    @patch('ai.views.AIService.generate_explanation', side_effect=AIProviderError(
        'secret diagnostic', code='missing_api_key',
    ))
    def test_provider_failure_keeps_question_without_saving_partial_turn(self, generate):
        response = self.post(question='Ma question à conserver')
        self.assertContains(response, 'Ma question à conserver')
        self.assertContains(response, "pas encore configuré")
        self.assertNotContains(response, 'secret diagnostic')
        self.assertEqual(AIMessage.objects.count(), 0)
        self.assertEqual(AIConversation.objects.count(), 0)

    @patch('ai.views.AIService.generate_explanation', return_value='Un exercice adapté.')
    def test_practice_mode_and_level_are_forwarded(self, generate):
        self.post(style='entrainement', level='simple')
        self.assertEqual(generate.call_args.kwargs['style'], 'entrainement')
        self.assertEqual(generate.call_args.kwargs['level'], 'simple')

    @patch('ai.views.AIService.generate_explanation', return_value='Une autre explication.')
    def test_reformulation_uses_saved_answer_not_client_supplied_text(self, generate):
        conversation = AIConversation.objects.create(user=self.user, lesson=self.lesson)
        AIMessage.objects.create(conversation=conversation, role='assistant', content='Réponse sauvegardée')
        self.post(conversation_id=conversation.pk, style='autrement', previous_answer='Texte falsifié')
        self.assertEqual(generate.call_args.kwargs['previous_answer'], 'Réponse sauvegardée')

    def test_lesson_link_preselects_context_and_login_is_required(self):
        response = self.client.get(reverse('ai:assistant_lesson', args=[self.lesson.pk]), follow=True)
        self.assertEqual(response.context['selected_lesson'], self.lesson)
        self.client.session.flush()
        self.assertEqual(self.client.get(self.url).status_code, 302)

    @patch('ai.views.AIService.generate_explanation', return_value='Réponse')
    def test_lesson_post_redirects_to_saved_conversation(self, generate):
        response = self.client.post(
            reverse('ai:assistant_lesson', args=[self.lesson.pk]),
            {'question': 'Aide-moi'},
        )
        self.assertTrue(response.url.startswith(self.url + '?c='))

    @patch.object(AIService, '_chat', return_value='Essaie de soustraire 2.')
    def test_service_sends_lesson_and_bounded_conversation_to_provider(self, chat):
        history = [
            {'role': 'user' if i % 2 == 0 else 'assistant', 'content': str(i)}
            for i in range(20)
        ]
        AIService().generate_explanation(
            self.lesson, 'Et ensuite?', style='entrainement', conversation_history=history,
        )
        sent = chat.call_args.args[0]
        self.assertEqual(len(sent), 14)
        self.assertEqual(sent[1]['content'], '8')
        self.assertIn(self.lesson.content, sent[-1]['content'])
        self.assertIn('Ne donne pas encore sa solution', sent[-1]['content'])

    @patch.object(AIService, '_chat', return_value=' ')
    def test_empty_provider_response_is_an_error(self, chat):
        with self.assertRaises(AIProviderError):
            AIService().generate_explanation(self.lesson, 'Aide-moi')


class QuizLatexJsonTests(SimpleTestCase):
    def setUp(self):
        self.service = AIService.__new__(AIService)

    def test_double_escaped_latex_backslashes_survive_json_parsing(self):
        raw = r'''{
          "questions": [{
            "text": "Calculer $\\frac{1}{2}$",
            "choices": [
              {"text": "$\\frac{1}{2}$", "is_correct": true},
              {"text": "1", "is_correct": false}
            ],
            "correct_answer": "$\\frac{1}{2}$",
            "explanation": "$\\beta$",
            "hint": "$\\sqrt{4}$"
          }]
        }'''

        data = self.service._validate_quiz_json(raw, 1)

        question = data['questions'][0]
        self.assertEqual(question['text'], r'Calculer $\frac{1}{2}$')
        self.assertEqual(question['choices'][0]['text'], r'$\frac{1}{2}$')
        self.assertEqual(question['correct_answer'], r'$\frac{1}{2}$')
        self.assertEqual(question['explanation'], r'$\beta$')
        self.assertEqual(question['hint'], r'$\sqrt{4}$')

    def test_single_backslashes_and_json_control_escapes_are_repaired(self):
        raw = r'''{
          "questions": [{
            "text": "$\forall x \in \mathbb{R}$",
            "choices": [
              {"text": "$\frac{1}{2}$", "is_correct": true},
              {"text": "1", "is_correct": false}
            ],
            "correct_answer": "$\frac{1}{2}$",
            "explanation": "$\beta + \times$",
            "hint": "$\right|x \neq 0$"
          }]
        }'''

        data = self.service._validate_quiz_json(raw, 1)

        question = data['questions'][0]
        self.assertEqual(question['text'], r'$\forall x \in \mathbb{R}$')
        self.assertEqual(question['correct_answer'], r'$\frac{1}{2}$')
        self.assertEqual(question['choices'][0]['text'], r'$\frac{1}{2}$')
        self.assertEqual(question['explanation'], r'$\beta + \times$')
        self.assertEqual(question['hint'], r'$\right|x \neq 0$')

    def test_repair_keeps_valid_json_escapes_and_fixes_invalid_latex_escapes(self):
        parsed = repair_latex_escapes(r'{"text":"line 1\n\sqrt{x}"}')

        self.assertEqual(parsed['text'], 'line 1\n' + r'\sqrt{x}')

    def test_quiz_prompt_requires_delimited_latex_and_json_escaped_slashes(self):
        prompt = build_quiz_prompt(
            'Terminale', 'Mathématiques', 'Limites', 'Contenu de la leçon',
            3, 'moyen',
        )

        self.assertIn('choices[].text', prompt)
        self.assertIn(r'\\forall', prompt)
        self.assertIn(r'\\frac', prompt)
        self.assertIn('encadre chaque expression mathématique', prompt)
        self.assertNotIn('INTERDIT d’utiliser du code LaTeX', prompt)

    def test_provider_prompt_uses_the_same_latex_rules(self):
        lesson = SimpleNamespace(get_ai_help=lambda: {
            'niveau': 'Terminale',
            'cours': 'Mathématiques',
            'lecon': 'Limites',
            'contenu': 'Cours de test',
        })
        provider = SimpleNamespace(name='test', model='test-model')
        raw = r'''{"questions":[{
          "text":"Calculer $\\frac{1}{2}$",
          "choices":[
            {"text":"$\\frac{1}{2}$","is_correct":true},
            {"text":"1","is_correct":false}
          ],
          "correct_answer":"$\\frac{1}{2}$",
          "explanation":"Explication",
          "hint":"Indice"
        }]}'''

        with (
            patch.object(AIService, '_chat', return_value=raw) as chat,
            patch.object(AIService, '_get_provider', return_value=provider),
        ):
            self.service.generate_quiz_from_lesson(lesson, question_count=1)

        provider_prompt = chat.call_args.args[0][-1]['content']
        self.assertIn(r'\\forall', provider_prompt)
        self.assertIn('encadre chaque expression mathématique', provider_prompt)
        self.assertNotIn('INTERDIT d’utiliser du code LaTeX', provider_prompt)
        self.assertNotIn('Description du quiz du professeur', provider_prompt)

    def test_quiz_description_has_priority_without_overriding_lesson_constraints(self):
        lesson = SimpleNamespace(get_ai_help=lambda: {
            'niveau': 'Terminale',
            'cours': 'Mathématiques',
            'lecon': 'Puissances',
            'contenu': 'Règles des puissances à exposants entiers.',
        })
        provider = SimpleNamespace(name='test', model='test-model')
        raw = r'''{"questions":[{
          "text":"Simplifier $2^3$",
          "choices":[
            {"text":"8","is_correct":true},
            {"text":"6","is_correct":false}
          ],
          "correct_answer":"8",
          "explanation":"Calcul direct.",
          "hint":"Multiplie trois facteurs."
        }]}'''
        description = (
            "Prioriser les puissances négatives et les calculs en plusieurs étapes."
        )

        with (
            patch.object(AIService, '_chat', return_value=raw) as chat,
            patch.object(AIService, '_get_provider', return_value=provider),
        ):
            self.service.generate_quiz_from_lesson(
                lesson,
                question_count=1,
                description=description,
            )

        provider_prompt = chat.call_args.args[0][-1]['content']
        self.assertIn(description, provider_prompt)
        self.assertIn('priorité principale', provider_prompt)
        self.assertIn('strictement dans le contenu de la leçon', provider_prompt)
