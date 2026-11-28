"""Sondages rapides du salon (professeur seulement, un vote par personne, noms réservés au
professeur, sondage clos) et mentions « @Prénom Nom » (validées, notifiées, sans abus)."""
from django.urls import reverse

from accounts.models import User
from notifications.models import Notification

from .models import ChatMessage, ChatPoll, ChatPollVote
from .test_moderation import ChatTestBase


class SondageTests(ChatTestBase):
    def creer(self, question='Avez-vous compris ?', options=('Oui', 'Non')):
        return self.post_json(reverse('chat:api_poll_create', args=[self.classroom.pk]),
                              {'question': question, 'options': list(options)})

    def voter(self, poll, option):
        return self.post_json(reverse('chat:api_poll_vote', args=[poll.pk]), {'option': option})

    def test_seul_le_professeur_cree(self):
        self.login_as(self.student)
        self.assertEqual(self.creer().status_code, 403)
        self.login_as(self.teacher)
        r = self.creer()
        self.assertEqual(r.status_code, 200)
        poll = ChatPoll.objects.get()
        self.assertEqual(poll.message.body, '📊 Avez-vous compris ?')
        self.assertEqual(r.json()['message']['poll']['options'][0]['text'], 'Oui')
        self.assertTrue(r.json()['message']['poll']['can_close'])

    def test_validation(self):
        self.login_as(self.teacher)
        self.assertEqual(self.creer(options=('Oui',)).status_code, 400)
        self.assertEqual(self.creer(question='').status_code, 400)
        self.assertEqual(self.creer(options=('Oui', 'oui')).status_code, 400)
        self.assertEqual(self.creer(options=[str(i) for i in range(7)]).status_code, 400)
        self.assertFalse(ChatPoll.objects.exists())

    def test_vote_change_retire_et_noms_pour_le_professeur(self):
        self.login_as(self.teacher)
        self.creer()
        poll = ChatPoll.objects.get()
        self.login_as(self.student)
        r = self.voter(poll, 0)
        options = r.json()['message']['poll']['options']
        self.assertEqual(options[0]['count'], 1)
        self.assertTrue(options[0]['mine'])
        self.assertNotIn('names', options[0])                 # l'élève ne voit pas qui a voté
        self.voter(poll, 1)                                     # change de choix
        self.assertEqual(list(ChatPollVote.objects.values_list('option', flat=True)), [1])
        self.voter(poll, 1)                                     # le même le retire
        self.assertFalse(ChatPollVote.objects.exists())
        self.voter(poll, 0)
        self.assertEqual(self.voter(poll, 5).status_code, 400)
        # Le professeur voit les noms, dans la liste des messages aussi.
        self.login_as(self.teacher)
        data = self.client.get(reverse('chat:api_messages', args=[self.classroom.pk])).json()
        sondage = [m for m in data['messages'] if m['poll']][0]['poll']
        self.assertEqual(sondage['options'][0]['names'], ['Amal'])
        self.assertEqual(sondage['total'], 1)

    def test_sondage_clos_et_hors_classe(self):
        self.login_as(self.teacher)
        self.creer()
        poll = ChatPoll.objects.get()
        self.login_as(self.student)
        self.assertEqual(self.post_json(reverse('chat:api_poll_close', args=[poll.pk])).status_code, 403)
        self.login_as(self.teacher)
        self.post_json(reverse('chat:api_poll_close', args=[poll.pk]))
        self.login_as(self.student)
        self.assertEqual(self.voter(poll, 0).status_code, 400)
        intrus = User.objects.create_user(username='intrus', email='i@example.test', role='student')
        self.login_as(intrus)
        self.assertEqual(self.voter(poll, 0).status_code, 403)


class MentionTests(ChatTestBase):
    def envoyer(self, body, mentions):
        return self.post_json(reverse('chat:api_send', args=[self.classroom.pk]), {'body': body, 'mentions': mentions})

    def test_mention_valide_notifiee(self):
        self.login_as(self.teacher)
        r = self.envoyer('@Amal peux-tu corriger au tableau ?', [self.student.pk])
        self.assertEqual(r.json()['message']['mentions'], [{'id': self.student.pk, 'name': 'Amal'}])
        n = Notification.objects.get(recipient=self.student, type='message')
        self.assertIn('vous a mentionné', n.title)
        self.assertIn(reverse('chat:room', args=[self.classroom.pk]), n.link)

    def test_mention_ignoree_si_absente_du_texte_ou_hors_classe(self):
        intrus = User.objects.create_user(username='zz', email='zz@example.test', role='student', first_name='Zed')
        self.login_as(self.teacher)
        r = self.envoyer('Bonjour à tous @Zed', [self.classmate.pk, intrus.pk, 'x'])
        self.assertEqual(r.json()['message']['mentions'], [])
        self.assertFalse(ChatMessage.objects.get().mentions.exists())
        self.assertFalse(Notification.objects.filter(type='message', title__contains='mentionné').exists())

    def test_on_ne_se_mentionne_pas_soi_meme(self):
        self.login_as(self.student)
        self.envoyer('@Amal moi', [self.student.pk])
        self.assertFalse(ChatMessage.objects.get().mentions.exists())
