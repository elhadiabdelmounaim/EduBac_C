"""Clic sur une notification du téléphone : la notification de l'application est marquée comme
lue (même groupée ou envoyée à toute la classe), seulement pour l'utilisateur, lien interne
uniquement, et retour sur la notification après une connexion."""
from urllib.parse import urlencode

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from notifications.models import Notification

PASSWORD = 'MotDePasse-Test-2026!'


@override_settings(EMAIL_NOTIFICATIONS_ENABLED=False)
class OuvertureDepuisTelephoneTests(TestCase):
    def setUp(self):
        self.eleve = User.objects.create_user(username='amal', email='amal@example.test', role='student',
                                              password=PASSWORD)
        self.autre = User.objects.create_user(username='badr', email='badr@example.test', role='student')

    def connecter(self, user):
        session = self.client.session
        session['user_id'] = user.pk
        session['role'] = user.role
        session['password_session_version'] = user.password_session_version
        session.save()

    def ouvrir(self, **params):
        return self.client.get(reverse('notifications:open_push') + '?' + urlencode(params))

    def test_lien_envoye_au_telephone(self):
        url = Notification.lien_telephone('/quizzes/7/', 'notif-3')
        self.assertTrue(url.startswith(reverse('notifications:open_push') + '?'))
        self.assertIn('lien=%2Fquizzes%2F7%2F', url)
        self.assertIn('groupe=notif-3', url)
        self.assertEqual(Notification.lien_telephone('https://pirate.example/', ''), reverse('notifications:open_push'))

    def test_clic_marque_lu_et_redirige(self):
        n = Notification.notify(self.eleve, 'Nouveau quiz', 'Les vecteurs', type='quiz', link='/quizzes/7/', send_email=False)
        n_autre = Notification.notify(self.autre, 'Nouveau quiz', 'Les vecteurs', type='quiz', link='/quizzes/7/', send_email=False)
        self.connecter(self.eleve)
        r = self.ouvrir(lien='/quizzes/7/', groupe=f'notif-{n.pk}')
        self.assertRedirects(r, '/quizzes/7/', fetch_redirect_response=False)
        n.refresh_from_db()
        n_autre.refresh_from_db()
        self.assertTrue(n.is_read)
        self.assertFalse(n_autre.is_read)               # jamais les notifications d'un autre

    def test_annonce_a_toute_la_classe_et_notification_groupee(self):
        Notification.notify_many([self.eleve, self.autre], 'Annonce — 1BAC', 'Contrôle lundi', type='message',
                                 link='/chat/classe/1/')
        Notification.notify(self.eleve, 'Messages', 'Nouveau message', type='message', link='/chat/direct/4/',
                            group_key='direct:4', send_email=False)
        self.connecter(self.eleve)
        self.ouvrir(lien='/chat/classe/1/', groupe='many-123')
        self.ouvrir(groupe='direct:4')
        self.assertFalse(Notification.objects.filter(recipient=self.eleve, is_read=False).exists())
        self.assertTrue(Notification.objects.filter(recipient=self.autre, is_read=False).exists())

    def test_lien_externe_refuse(self):
        self.connecter(self.eleve)
        for lien in ('https://pirate.example/', '//pirate.example/', '/\\pirate.example'):
            with self.subTest(lien=lien):
                r = self.ouvrir(lien=lien)
                self.assertRedirects(r, reverse('notifications:history'), fetch_redirect_response=False)

    def test_session_expiree_connexion_puis_notification_lue(self):
        n = Notification.notify(self.eleve, 'Inscription acceptée', 'Bienvenue', type='account',
                                link='/compte/tableau-de-bord/', send_email=False)
        r = self.ouvrir(lien='/compte/tableau-de-bord/', groupe=f'notif-{n.pk}')
        self.assertRedirects(r, reverse('accounts:login'), fetch_redirect_response=False)
        self.eleve.email_verified = True
        self.eleve.recovery_code_hash = 'deja-un-code'      # élève qui a déjà son code de récupération
        self.eleve.save()
        r = self.client.post(reverse('accounts:login'), {'username': 'amal', 'password': PASSWORD})
        self.assertTrue(r['Location'].startswith(reverse('notifications:open_push')))
        r = self.client.get(r['Location'])
        self.assertRedirects(r, '/compte/tableau-de-bord/', fetch_redirect_response=False)
        n.refresh_from_db()
        self.assertTrue(n.is_read)

    def test_premiere_connexion_code_de_recuperation_puis_notification(self):
        self.eleve.email_verified = True
        self.eleve.save()
        self.ouvrir(lien='/quizzes/7/')
        r = self.client.post(reverse('accounts:login'), {'username': 'amal', 'password': PASSWORD})
        self.assertTrue(r['Location'].startswith(reverse('accounts:recovery_code') + '?premiere=1'))
        self.assertIn('suite=' + '%2Fnotifications%2Ftelephone%2Fouvrir%2F', r['Location'])
