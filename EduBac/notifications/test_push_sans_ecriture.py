"""SQLite n'accepte qu'une écriture à la fois : un abonnement inchangé ne réécrit rien, et les
transactions qui écrivent réservent la base dès le départ (pas de « database is locked »)."""
import json

import django
from django.conf import settings
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from accounts.models import User
from notifications.models import PushSubscription

ABONNEMENT = {
    'endpoint': 'https://fcm.googleapis.com/fcm/send/appareil-1',
    'keys': {'p256dh': 'B' * 87, 'auth': 'a' * 22},
}


@override_settings(WEBPUSH_VAPID_PUBLIC_KEY='publique', WEBPUSH_VAPID_PRIVATE_KEY='privee')
class AbonnementSansEcritureTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(username='nadia', email='n@x.test', role='teacher')
        session = self.client.session
        session['user_id'] = self.user.pk
        session['role'] = self.user.role
        session['password_session_version'] = self.user.password_session_version
        session.save()
        # La présence (middleware) est déjà notée : seules les écritures de l'abonnement comptent.
        self.client.get(reverse('accounts:dashboard'))

    def envoyer(self, corps):
        return self.client.post(reverse('notifications:push_subscribe'), data=json.dumps(corps),
                                content_type='application/json')

    @staticmethod
    def ecritures(requetes):
        return [q['sql'] for q in requetes
                if q['sql'].lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE'))
                and 'push' in q['sql'].lower()]

    def test_abonnement_inchange_ne_reecrit_rien(self):
        self.assertEqual(self.envoyer(ABONNEMENT).status_code, 200)
        self.assertEqual(PushSubscription.objects.filter(user=self.user).count(), 1)
        with CaptureQueriesContext(connection) as requetes:
            self.assertEqual(self.envoyer(ABONNEMENT).status_code, 200)
        self.assertEqual(self.ecritures(requetes.captured_queries), [])

    def test_cles_changees_ou_echecs_mis_a_jour(self):
        self.envoyer(ABONNEMENT)
        PushSubscription.objects.update(failures=2)
        nouveau = {'endpoint': ABONNEMENT['endpoint'], 'keys': {'p256dh': 'C' * 87, 'auth': 'b' * 22}}
        with CaptureQueriesContext(connection) as requetes:
            self.envoyer(nouveau)
        self.assertTrue(self.ecritures(requetes.captured_queries))
        abonnement = PushSubscription.objects.get()
        self.assertEqual((abonnement.p256dh, abonnement.failures), ('C' * 87, 0))

    def test_appareil_d_un_autre_compte_rattache(self):
        autre = User.objects.create(username='omar', email='o@x.test', role='student')
        PushSubscription.objects.create(user=autre, endpoint=ABONNEMENT['endpoint'],
                                        p256dh=ABONNEMENT['keys']['p256dh'], auth=ABONNEMENT['keys']['auth'])
        self.envoyer(ABONNEMENT)
        self.assertEqual(PushSubscription.objects.get().user, self.user)


class ReglagesSQLiteTests(TestCase):
    def test_transactions_immediates_si_django_le_permet(self):
        from config.settings import sqlite_options
        options = sqlite_options()
        self.assertEqual(options['timeout'], 20)
        if django.VERSION >= (5, 1):
            self.assertEqual(options['transaction_mode'], 'IMMEDIATE')
        else:
            self.assertNotIn('transaction_mode', options)
        if settings.DATABASES['default']['ENGINE'].endswith('sqlite3'):
            self.assertEqual(settings.DATABASES['default']['OPTIONS'], options)
