from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from education.models import Course, Lesson
from .models import AIConversation, AIMessage
from .providers import AIProviderError
from .services import AIService


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
