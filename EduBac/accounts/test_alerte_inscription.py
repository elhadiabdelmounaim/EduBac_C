"""Alerte de validation : après sa demande d'inscription, l'élève peut abonner son téléphone ;
quand l'administrateur accepte, la notification part vers ce téléphone."""
import json
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from classrooms.models import Classroom
from notifications.models import PushSubscription

CLES = {'WEBPUSH_VAPID_PUBLIC_KEY': 'cle-publique-de-test', 'WEBPUSH_VAPID_PRIVATE_KEY': 'cle-privee-de-test'}
ABONNEMENT = {
    'endpoint': 'https://fcm.googleapis.com/fcm/send/appareil-eleve-123',
    'keys': {'p256dh': 'B' * 87, 'auth': 'a' * 22},
}


@override_settings(**CLES)
class AlerteInscriptionTests(TestCase):
    def setUp(self):
        Classroom.objects.create(name='1BAC', niveau='tronc_commun', code='CODE01')
        self.admin = User.objects.create(username='admin', email='admin@example.test',
                                         is_staff=True, is_superuser=True)
        self.donnees = {'name': 'Yassine Amrani', 'username': 'yassine', 'password': 'LongPass123!',
                        'password2': 'LongPass123!', 'class_code': 'CODE01'}

    def inscrire(self):
        response = self.client.post(reverse('accounts:register_student'), self.donnees)
        self.assertRedirects(response, reverse('accounts:inscription_envoyee'))
        return User.objects.get(username='yassine')

    def abonner(self, client=None, corps=None):
        return (client or self.client).post(
            reverse('notifications:push_subscribe_inscription'),
            data=json.dumps(corps or ABONNEMENT), content_type='application/json',
        )

    def decider(self, eleve, action):
        admin = self.client_class()
        session = admin.session
        session['user_id'] = self.admin.pk
        session['role'] = self.admin.role
        session['password_session_version'] = self.admin.password_session_version
        session.save()
        return admin.post(reverse('accounts:review_registration', args=[eleve.pk]), {'action': action})

    def test_page_demande_envoyee_propose_l_alerte(self):
        self.inscrire()
        page = self.client.get(reverse('accounts:inscription_envoyee'))
        self.assertContains(page, 'Demande envoyée')
        self.assertContains(page, 'yassine')
        self.assertContains(page, 'data-alerte-inscription')
        self.assertContains(page, reverse('notifications:push_subscribe_inscription'))

    def test_sans_cles_push_pas_de_bouton_mais_la_page_reste(self):
        self.inscrire()
        with override_settings(WEBPUSH_VAPID_PUBLIC_KEY='', WEBPUSH_VAPID_PRIVATE_KEY=''):
            page = self.client.get(reverse('accounts:inscription_envoyee'))
        self.assertContains(page, 'Demande envoyée')
        self.assertNotContains(page, 'data-alerte-inscription')
        self.assertContains(page, 'Aller à la connexion')

    def test_page_sans_inscription_renvoie_a_la_connexion(self):
        self.assertRedirects(self.client.get(reverse('accounts:inscription_envoyee')), reverse('accounts:login'))

    def test_abonnement_lie_a_l_eleve_puis_notification_a_la_validation(self):
        eleve = self.inscrire()
        self.assertEqual(self.abonner().status_code, 200)
        abonnement = PushSubscription.objects.get(endpoint=ABONNEMENT['endpoint'])
        self.assertEqual(abonnement.user, eleve)

        with mock.patch('notifications.push.push_to_users') as push, \
                self.captureOnCommitCallbacks(execute=True):
            self.decider(eleve, 'approve')
        envois = [c for c in push.call_args_list if eleve.pk in list(c.args[0])]
        self.assertEqual(len(envois), 1)
        self.assertEqual(envois[0].args[1], 'Inscription acceptée — EduBac')
        self.assertIn('Connectez-vous', envois[0].args[2])

        # Demande acceptée : la page le dit, et on ne peut plus abonner via l'inscription.
        self.assertContains(self.client.get(reverse('accounts:inscription_envoyee')), 'Demande acceptée')
        self.assertEqual(self.abonner().status_code, 403)

    def test_refus_supprime_l_abonnement(self):
        eleve = self.inscrire()
        self.abonner()
        self.decider(eleve, 'reject')
        self.assertFalse(PushSubscription.objects.filter(endpoint=ABONNEMENT['endpoint']).exists())

    def test_un_autre_appareil_ne_peut_pas_s_abonner_pour_l_eleve(self):
        self.inscrire()
        autre = self.client_class()
        self.assertEqual(self.abonner(client=autre).status_code, 403)
        self.assertFalse(PushSubscription.objects.exists())

    def test_abonnement_invalide_refuse(self):
        self.inscrire()
        self.assertEqual(self.abonner(corps={'endpoint': 'https://pirate.example/x', 'keys': ABONNEMENT['keys']}).status_code, 400)
        self.assertEqual(self.client.post(reverse('notifications:push_subscribe_inscription'), data='{}',
                                          content_type='application/json').status_code, 400)
        self.assertFalse(PushSubscription.objects.exists())

    def test_admin_voit_l_activation_des_alertes(self):
        session = self.client.session
        session['user_id'] = self.admin.pk
        session['role'] = self.admin.role
        session['password_session_version'] = self.admin.password_session_version
        session.save()
        self.assertContains(self.client.get(reverse('accounts:admin_dashboard')), 'data-alerte-admin')
