import json
from unittest.mock import patch
from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from education.models import Course, Lesson
from .models import AIConversation, AIMessage
from .providers import AIProviderError
from .prompts import build_quiz_prompt
from .providers.groq import GroqProvider, _retry_after_seconds, bounded_retry_after
from .providers.base import http_error_code
from .services import AIService, _rate_limit_delay, public_quiz_error, repair_latex_escapes


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

    def test_already_escaped_latex_survives_an_invalid_escape_elsewhere(self):
        raw = r'''{
          "questions": [{
            "text": "Aire $\\sqrt{x}$ et $\alpha$",
            "choices": [
              {"text": "$\\sqrt{x}$", "is_correct": true},
              {"text": "$\frac{1}{2}$", "is_correct": false},
              {"text": "1", "is_correct": false},
              {"text": "0", "is_correct": false}
            ],
            "correct_answer": "$\\sqrt{x}$",
            "explanation": "$\\\sin x$ et $\underbrace{x}$",
            "hint": "$\neq 0$"
          }]
        }'''

        data = self.service._validate_quiz_json(raw, 1)

        question = data['questions'][0]
        self.assertEqual(question['text'], r'Aire $\sqrt{x}$ et $\alpha$')
        self.assertEqual(question['choices'][0]['text'], r'$\sqrt{x}$')
        self.assertEqual(question['choices'][1]['text'], r'$\frac{1}{2}$')
        self.assertEqual(question['explanation'], r'$\sin x$ et $\underbrace{x}$')
        self.assertEqual(question['hint'], r'$\neq 0$')

    def _lesson(self):
        return SimpleNamespace(pk=None, get_ai_help=lambda: {
            'niveau': 'Terminale',
            'cours': 'Mathématiques',
            'lecon': 'Racines',
            'contenu': 'Racine carrée et identités.',
        })

    def _one_question(self, text='Calculer $2+2$'):
        return json.dumps({
            'questions': [{
                'text': text,
                'choices': [
                    {'text': '4', 'is_correct': True},
                    {'text': '3', 'is_correct': False},
                ],
                'explanation': 'Somme des deux nombres.',
                'hint': 'Addition',
            }],
        })

    def test_short_rate_limit_waits_once_then_retries(self):
        provider = SimpleNamespace(name='groq', model='llama-3.1-8b-instant')
        rate_limit = AIProviderError(
            'Please try again in 20.6475s.',
            code='rate_limit',
            retry_after=20.6475,
        )
        with (
            patch.object(AIService, '_chat', side_effect=[rate_limit, self._one_question()]) as chat,
            patch.object(AIService, '_get_provider', return_value=provider),
            patch('ai.services.time.sleep') as sleep,
        ):
            data = self.service.generate_quiz_from_lesson(self._lesson(), question_count=1)

        self.assertEqual(data['questions'][0]['correct_answer'], '4')
        self.assertEqual(chat.call_count, 2)
        sleep.assert_called_once()
        self.assertAlmostEqual(sleep.call_args.args[0], 20.6475, places=3)

    def test_long_rate_limit_returns_the_existing_error_without_waiting(self):
        provider = SimpleNamespace(name='groq', model='llama-3.1-8b-instant')
        rate_limit = AIProviderError('wait', code='rate_limit', retry_after=597)
        with (
            patch.object(AIService, '_chat', side_effect=[rate_limit, self._one_question()]) as chat,
            patch.object(AIService, '_get_provider', return_value=provider),
            patch('ai.services.time.sleep') as sleep,
        ):
            with self.assertRaises(AIProviderError) as error:
                self.service.generate_quiz_from_lesson(self._lesson(), question_count=1)

        self.assertEqual(error.exception.code, 'rate_limit')
        self.assertEqual(chat.call_count, 1)
        sleep.assert_not_called()
        self.assertIn('10 minutes', public_quiz_error(error.exception))
        self.assertIsNone(bounded_retry_after(597))
        self.assertAlmostEqual(bounded_retry_after(20.6475), 20.6475, places=3)

    def test_broken_json_regenerates_only_the_missing_question(self):
        provider = SimpleNamespace(name='groq', model='llama-3.1-8b-instant')
        kept = json.dumps({
            'text': 'Question valide à conserver.',
            'choices': [
                {'text': 'oui', 'is_correct': True},
                {'text': 'non', 'is_correct': False},
            ],
            'explanation': 'Déjà correcte.',
            'hint': 'Lis le cours.',
        })
        broken = 'avant ' + kept + ' { "text": "cassée", "choices": [ '
        with (
            patch.object(
                AIService, '_chat',
                side_effect=[broken, self._one_question('Question de remplacement.')],
            ) as chat,
            patch.object(AIService, '_get_provider', return_value=provider),
            patch('ai.services.time.sleep'),
        ):
            data = self.service.generate_quiz_from_lesson(self._lesson(), question_count=2)

        self.assertEqual(
            [question['text'] for question in data['questions']],
            ['Question valide à conserver.', 'Question de remplacement.'],
        )
        self.assertEqual(chat.call_count, 2)
        self.assertIn('CORRIGE uniquement', chat.call_args_list[1].args[0][-1]['content'])

    def test_timeout_bad_request_and_not_found_do_not_regenerate_the_quiz(self):
        lesson = SimpleNamespace(pk=None, get_ai_help=lambda: {
            'niveau': 'Terminale',
            'cours': 'Mathématiques',
            'lecon': 'Racines',
            'contenu': 'Racine carrée.',
        })
        provider = SimpleNamespace(name='groq', model='openai/gpt-oss-120b')
        for code in ('timeout', 'bad_request', 'not_found'):
            with self.subTest(code=code):
                with (
                    patch.object(
                        AIService, '_chat',
                        side_effect=AIProviderError('provider failed', code=code),
                    ) as chat,
                    patch.object(AIService, '_get_provider', return_value=provider),
                    patch('ai.services.time.sleep'),
                ):
                    with self.assertRaises(AIProviderError) as error:
                        self.service.generate_quiz_from_lesson(lesson, question_count=1)
                self.assertEqual(error.exception.code, code)
                self.assertEqual(chat.call_count, 1)

    def test_generation_stops_when_the_deadline_is_already_spent(self):
        lesson = SimpleNamespace(pk=None, get_ai_help=lambda: {
            'niveau': 'Terminale',
            'cours': 'Mathématiques',
            'lecon': 'Racines',
            'contenu': 'Racine carrée.',
        })
        provider = SimpleNamespace(name='groq', model='test-model')
        with (
            patch('ai.services.QUIZ_GENERATION_DEADLINE', 0),
            patch.object(AIService, '_chat') as chat,
            patch.object(AIService, '_get_provider', return_value=provider),
        ):
            with self.assertRaises(AIProviderError) as error:
                self.service.generate_quiz_from_lesson(lesson, question_count=1)
        self.assertEqual(error.exception.code, 'timeout')
        chat.assert_not_called()
        self.assertIn('trop de temps', public_quiz_error(error.exception))

    def test_http_status_codes_map_to_quiz_errors(self):
        self.assertEqual(http_error_code(400), 'bad_request')
        self.assertEqual(http_error_code(404), 'not_found')
        self.assertEqual(http_error_code(429), 'rate_limit')
        self.assertEqual(public_quiz_error(AIProviderError('nope', code='bad_request')),
                         'Le fournisseur IA a rejeté la requête (400).')
        self.assertEqual(public_quiz_error(AIProviderError('nope', code='not_found')),
                         'Le modèle IA est introuvable (404).')
        self.assertEqual(public_quiz_error(AIProviderError('nope', code='invalid_json')),
                         "La réponse de l'IA n'est pas un JSON valide.")

    def test_groq_retry_after_reads_the_header_then_the_message(self):
        header_error = SimpleNamespace(
            response=SimpleNamespace(headers={'retry-after-ms': '20647.5'}),
        )
        self.assertAlmostEqual(_retry_after_seconds(header_error), 20.6475, places=3)
        self.assertAlmostEqual(_rate_limit_delay(AIProviderError(
            'Please try again in 20.6475s.', code='rate_limit',
        )), 20.9975, places=3)
        class MillisecondHint(Exception):
            response = SimpleNamespace(headers={'retry-after': '597'})

            def __str__(self):
                return 'Please try again in 597ms'

        self.assertAlmostEqual(_retry_after_seconds(MillisecondHint()), 0.597, places=3)
        self.assertIn(
            '10 minutes',
            public_quiz_error(AIProviderError('wait', code='rate_limit', retry_after=597)),
        )

    def test_rate_limit_keeps_the_configured_groq_model(self):
        import httpx
        from groq import RateLimitError

        provider = GroqProvider(api_key='test-key', model='openai/gpt-oss-120b')
        request = httpx.Request('POST', 'https://api.groq.com/openai/v1/chat/completions')
        response = httpx.Response(429, headers={'retry-after': '597'}, request=request)
        limited = RateLimitError('Please try again in 597s', response=response, body=None)
        calls = []

        class Completions:
            def create(self, **kwargs):
                calls.append(kwargs['model'])
                raise limited

        class Client:
            class chat:  # noqa: N801
                completions = Completions()

        with patch.object(provider, '_get_client', return_value=Client()):
            with self.assertRaises(AIProviderError) as error:
                provider.chat([{'role': 'user', 'content': 'quiz'}])

        self.assertEqual(error.exception.code, 'rate_limit')
        self.assertEqual(calls, ['openai/gpt-oss-120b'])

    def _groq_client(self, create):
        class Completions:
            def create(self, **kwargs):
                return create(kwargs)

        class Client:
            class chat:  # noqa: N801
                completions = Completions()

        return Client()

    def test_decommissioned_llama_uses_gpt_oss_reasoning_when_content_is_empty(self):
        import httpx
        from groq import APIStatusError

        provider = GroqProvider(api_key='test-key', model='llama-3.1-8b-instant')
        request = httpx.Request('POST', 'https://api.groq.com/openai/v1/chat/completions')
        missing = APIStatusError(
            'The model does not exist',
            response=httpx.Response(404, request=request),
            body=None,
        )
        calls = []

        class Message:
            content = ''
            reasoning = self._one_question('Depuis le raisonnement')

        class Choice:
            message = Message()

        class Response:
            choices = [Choice()]

        def create(kwargs):
            calls.append(kwargs)
            if kwargs['model'] == 'llama-3.1-8b-instant':
                raise missing
            return Response()

        with patch.object(provider, '_get_client', return_value=self._groq_client(create)):
            text = provider.chat([{'role': 'user', 'content': 'quiz'}], json_mode=True)

        self.assertIn('Depuis le raisonnement', text)
        self.assertEqual(
            [call['model'] for call in calls],
            ['llama-3.1-8b-instant', 'openai/gpt-oss-20b'],
        )
        self.assertEqual(calls[1]['reasoning_effort'], 'low')
        self.assertEqual(calls[1]['response_format'], {'type': 'json_object'})
        data = self.service._parse_quiz_json(text)
        self.assertEqual(data['questions'][0]['text'], 'Depuis le raisonnement')

    def test_json_validate_failed_returns_the_rejected_generation(self):
        import httpx
        from groq import APIStatusError

        provider = GroqProvider(api_key='test-key', model='openai/gpt-oss-20b')
        request = httpx.Request('POST', 'https://api.groq.com/openai/v1/chat/completions')
        rejected = (
            r'{"questions":[{"text":"Aire $\sqrt{x}$","choices":['
            r'{"text":"1","is_correct":true},{"text":"2","is_correct":false}]}]}'
        )
        error = APIStatusError(
            'json_validate_failed',
            response=httpx.Response(400, request=request),
            body={'error': {
                'message': 'Failed to validate JSON',
                'code': 'json_validate_failed',
                'failed_generation': rejected,
            }},
        )
        calls = []

        def create(kwargs):
            calls.append(kwargs['model'])
            raise error

        with patch.object(provider, '_get_client', return_value=self._groq_client(create)):
            text = provider.chat([{'role': 'user', 'content': 'quiz'}], json_mode=True)

        self.assertEqual(calls, ['openai/gpt-oss-20b'])
        self.assertIn('questions', text)
        questions = self.service._load_quiz_for_repair(text, 1)['questions']
        self.assertEqual(questions[0]['text'], r'Aire $\sqrt{x}$')

    def test_rejected_reasoning_effort_retries_the_same_model(self):
        import httpx
        from groq import APIStatusError

        provider = GroqProvider(api_key='test-key', model='openai/gpt-oss-20b')
        request = httpx.Request('POST', 'https://api.groq.com/openai/v1/chat/completions')
        rejected = APIStatusError(
            'reasoning_effort is not supported',
            response=httpx.Response(400, request=request),
            body={'error': {'message': 'reasoning_effort is not supported'}},
        )
        calls = []

        class Message:
            content = self._one_question()
            reasoning = ''

        class Choice:
            message = Message()

        class Response:
            choices = [Choice()]

        def create(kwargs):
            calls.append(dict(kwargs))
            if 'reasoning_effort' in kwargs:
                raise rejected
            return Response()

        with patch.object(provider, '_get_client', return_value=self._groq_client(create)):
            text = provider.chat([{'role': 'user', 'content': 'quiz'}])

        self.assertEqual([call['model'] for call in calls], ['openai/gpt-oss-20b', 'openai/gpt-oss-20b'])
        self.assertNotIn('reasoning_effort', calls[1])
        self.assertIn('questions', text)

    def test_harmony_final_channel_is_the_quiz_json(self):
        payload = self._one_question('Question finale')
        raw = (
            '<|channel|>analysis<|message|>plan {not json<|end|>'
            '<|start|>assistant<|channel|>final<|message|>' + payload
        )
        data = self.service._parse_quiz_json(raw)
        self.assertEqual(data['questions'][0]['text'], 'Question finale')

    def test_think_block_is_removed_before_json_parse(self):
        raw = '<think>Je calcule {presque} le JSON.</think>\n' + self._one_question('Après think')
        data = self.service._parse_quiz_json(raw)
        self.assertEqual(data['questions'][0]['text'], 'Après think')

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
