"""Réactions aux messages : une par personne et par message, droits, confidentialité des noms
(professeur seulement), synchronisation et nombre de requêtes constant."""
from datetime import time, timedelta

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from .models import (
    ChatBlock,
    ChatMessage,
    ChatMute,
    DirectConversation,
    DirectMessage,
    MessageReaction,
    PrivateConversation,
    PrivateMessage,
)
from .test_moderation import ChatTestBase


class ReactionTests(ChatTestBase):
    def setUp(self):
        super().setUp()
        self.message = ChatMessage.objects.create(room=self.room, sender=self.teacher, body='La dérivée de $x^2$ est $2x$.')

    def react(self, emoji, kind='class', message=None):
        message = message or self.message
        return self.post_json(reverse('chat:api_message_react', args=[kind, message.pk]), {'emoji': emoji})

    def reactions(self, response):
        return {r['emoji']: r for r in response.json()['message']['reactions']}

    def test_ajouter_remplacer_retirer(self):
        self.login_as(self.student)
        r = self.react('👍')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.reactions(r)['👍']['count'], 1)
        self.assertTrue(self.reactions(r)['👍']['mine'])
        r = self.react('❓')                       # une autre réaction remplace la première
        self.assertEqual(set(self.reactions(r)), {'❓'})
        self.assertEqual(MessageReaction.objects.count(), 1)
        r = self.react('❓')                       # la même la retire
        self.assertEqual(r.json()['message']['reactions'], [])
        self.assertFalse(MessageReaction.objects.exists())

    def test_reaction_inconnue_et_message_supprime(self):
        self.login_as(self.student)
        self.assertEqual(self.react('🍕').status_code, 400)
        self.message.soft_delete(self.teacher)
        self.assertEqual(self.react('👍').status_code, 400)

    def test_intrus_et_sourdine(self):
        from accounts.models import User
        intrus = User.objects.create_user(username='intrus', email='i@example.test', role='student')
        self.login_as(intrus)
        self.assertEqual(self.react('👍').status_code, 404)
        ChatMute.objects.create(room=self.room, user=self.student, until=timezone.now() + timedelta(hours=1),
                                created_by=self.teacher)
        self.login_as(self.student)
        r = self.react('👍')
        self.assertEqual(r.status_code, 403)
        self.assertIn('réagir', r.json()['error'])

    def test_heures_de_silence_mais_mode_annonces_permis(self):
        self.room.is_locked = True
        self.room.save()
        self.login_as(self.student)
        self.assertEqual(self.react('✅').status_code, 200)     # les élèves peuvent répondre ✅ à une annonce
        maintenant = timezone.localtime().time()
        self.room.quiet_hours_start = time(0, 0)
        self.room.quiet_hours_end = time(23, 59, 59)
        self.room.save()
        if time(0, 0) <= maintenant <= time(23, 59, 59):
            self.assertEqual(self.react('👍').status_code, 403)
        self.login_as(self.teacher)
        self.assertEqual(self.react('👍').status_code, 200)     # le professeur n'est jamais limité

    def test_noms_visibles_seulement_par_le_professeur(self):
        self.login_as(self.student)
        self.react('❓')
        self.login_as(self.classmate)
        self.react('❓')
        url = reverse('chat:api_messages', args=[self.classroom.pk])
        eleve = self.client.get(url).json()['messages'][0]['reactions']
        self.assertEqual(eleve[0]['count'], 2)
        self.assertNotIn('names', eleve[0])
        self.login_as(self.teacher)
        prof = self.client.get(url).json()['messages'][0]['reactions']
        self.assertEqual(sorted(prof[0]['names']), ['Amal', 'Badr'])
        self.assertFalse(prof[0]['mine'])

    def test_synchronisation_des_autres_navigateurs(self):
        url = reverse('chat:api_messages', args=[self.classroom.pk])
        self.login_as(self.classmate)
        debut = self.client.get(url).json()
        self.login_as(self.student)
        self.react('✅')
        self.login_as(self.classmate)
        suite = self.client.get(url, {'after_id': self.message.pk, 'since': debut['server_time']}).json()
        self.assertEqual([m['id'] for m in suite['messages']], [self.message.pk])
        self.assertEqual(suite['messages'][0]['reactions'][0]['emoji'], '✅')

    def test_requetes_constantes(self):
        for i in range(30):
            m = ChatMessage.objects.create(room=self.room, sender=self.student, body=f'm{i}')
            MessageReaction.objects.create(kind='class', message_id=m.pk, user=self.classmate, emoji='👍')
        url = reverse('chat:api_messages', args=[self.classroom.pk])
        self.login_as(self.teacher)
        self.client.get(url)
        with CaptureQueriesContext(connection) as peu:
            self.client.get(url)
        for i in range(30):
            m = ChatMessage.objects.create(room=self.room, sender=self.student, body=f'n{i}')
            MessageReaction.objects.create(kind='class', message_id=m.pk, user=self.student, emoji='✅')
        with CaptureQueriesContext(connection) as beaucoup:
            self.client.get(url)
        self.assertEqual(len(peu.captured_queries), len(beaucoup.captured_queries))

    def test_consultation_et_message_individuel(self):
        conversation = PrivateConversation.objects.create(classroom=self.classroom, student=self.student,
                                                          teacher=self.teacher)
        prive = PrivateMessage.objects.create(conversation=conversation, sender=self.teacher, body='Revois la propriété 3.')
        self.login_as(self.student)
        r = self.react('✅', kind='consultation', message=prive)
        self.assertEqual(r.status_code, 200)
        self.login_as(self.teacher)
        liste = self.client.get(reverse('chat:api_private_messages', args=[conversation.pk])).json()
        self.assertEqual(liste['messages'][0]['reactions'][0]['emoji'], '✅')
        self.login_as(self.classmate)
        self.assertEqual(self.react('✅', kind='consultation', message=prive).status_code, 404)

        self.room.allow_student_direct = True
        self.room.save()
        direct, _ = DirectConversation.get_or_create_for(self.student, self.classmate, self.classroom)
        message = DirectMessage.objects.create(conversation=direct, sender=self.student, body='Salut')
        self.login_as(self.classmate)
        self.assertEqual(self.react('😂', kind='direct', message=message).status_code, 200)
        ChatBlock.objects.create(blocker=self.student, blocked=self.classmate)
        self.assertEqual(self.react('👍', kind='direct', message=message).status_code, 403)

    def test_suppression_du_message_masque_les_reactions(self):
        self.login_as(self.student)
        self.react('👍')
        self.message.soft_delete(self.teacher)
        self.login_as(self.teacher)
        data = self.client.get(reverse('chat:api_messages', args=[self.classroom.pk])).json()
        self.assertEqual(data['messages'][0]['reactions'], [])
        self.assertTrue(data['room']['can_react'])
