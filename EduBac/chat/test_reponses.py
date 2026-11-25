"""Répondre à un message précis dans les consultations et les messages individuels : citation,
même conversation seulement, message supprimé masqué, requêtes constantes."""
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .models import DirectConversation, DirectMessage, PrivateConversation, PrivateMessage
from .test_moderation import ChatTestBase


class ReponsesTests(ChatTestBase):
    def setUp(self):
        super().setUp()
        self.consultation = PrivateConversation.objects.create(
            classroom=self.classroom, student=self.student, teacher=self.teacher,
        )
        self.question = PrivateMessage.objects.create(
            conversation=self.consultation, sender=self.student,
            body='Je ne comprends pas pourquoi $x^2 \\geq 0$.',
        )

    def envoyer(self, url, body, reply_to):
        return self.post_json(url, {'body': body, 'reply_to': reply_to})

    def test_reponse_dans_une_consultation(self):
        self.login_as(self.teacher)
        url = reverse('chat:api_private_send', args=[self.consultation.pk])
        r = self.envoyer(url, 'Un carré est toujours positif.', self.question.pk)
        self.assertEqual(r.status_code, 200)
        cite = r.json()['message']['reply_to']
        self.assertEqual(cite['id'], self.question.pk)
        self.assertEqual(cite['sender_name'], 'Amal')
        self.assertIn('$x^2', cite['body'])
        self.assertEqual(PrivateMessage.objects.latest('pk').reply_to, self.question)
        self.login_as(self.student)
        liste = self.client.get(reverse('chat:api_private_messages', args=[self.consultation.pk])).json()
        self.assertEqual(liste['messages'][-1]['reply_to']['id'], self.question.pk)

    def test_message_d_une_autre_conversation_jamais_cite(self):
        autre = PrivateConversation.objects.create(classroom=self.classroom, student=self.classmate,
                                                   teacher=self.teacher)
        secret = PrivateMessage.objects.create(conversation=autre, sender=self.classmate, body='Secret')
        self.login_as(self.student)
        url = reverse('chat:api_private_send', args=[self.consultation.pk])
        r = self.envoyer(url, 'Je tente de citer', secret.pk)
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.json()['message']['reply_to'])
        self.assertIsNone(PrivateMessage.objects.latest('pk').reply_to)
        self.assertEqual(self.envoyer(url, 'Identifiant invalide', 'abc').status_code, 200)

    def test_message_cite_supprime(self):
        self.login_as(self.teacher)
        url = reverse('chat:api_private_send', args=[self.consultation.pk])
        self.envoyer(url, 'Réponse', self.question.pk)
        self.question.soft_delete(self.student)
        liste = self.client.get(reverse('chat:api_private_messages', args=[self.consultation.pk])).json()
        self.assertEqual(liste['messages'][-1]['reply_to']['body'], 'Message supprimé')
        self.assertNotIn('comprends', str(liste['messages']))
        # Un message déjà supprimé ne peut plus être cité.
        r = self.envoyer(url, 'Encore', self.question.pk)
        self.assertIsNone(r.json()['message']['reply_to'])

    def test_reponse_dans_un_message_individuel(self):
        self.room.allow_student_direct = True
        self.room.save()
        direct, _ = DirectConversation.get_or_create_for(self.student, self.classmate, self.classroom)
        premier = DirectMessage.objects.create(conversation=direct, sender=self.classmate, body='Tu as fini le devoir ?')
        self.login_as(self.student)
        r = self.envoyer(reverse('chat:api_direct_send', args=[direct.pk]), 'Oui !', premier.pk)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['message']['reply_to']['body'], 'Tu as fini le devoir ?')

    def test_requetes_constantes(self):
        url = reverse('chat:api_private_messages', args=[self.consultation.pk])
        for i in range(20):
            PrivateMessage.objects.create(conversation=self.consultation, sender=self.teacher,
                                          body=f'r{i}', reply_to=self.question)
        self.login_as(self.student)
        self.client.get(url)
        with CaptureQueriesContext(connection) as peu:
            self.client.get(url)
        for i in range(20):
            PrivateMessage.objects.create(conversation=self.consultation, sender=self.teacher,
                                          body=f's{i}', reply_to=self.question)
        with CaptureQueriesContext(connection) as beaucoup:
            self.client.get(url)
        self.assertEqual(len(peu.captured_queries), len(beaucoup.captured_queries))
