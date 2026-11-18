import json
from unittest import mock

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from chat.models import ClassChatRoom, PrivateConversation
from classrooms.models import Classroom

from . import push
from .models import Notification, PushSubscription

PUBLIC, PRIVATE = push.generate_vapid_keys()
KEYS = dict(WEBPUSH_VAPID_PUBLIC_KEY=PUBLIC, WEBPUSH_VAPID_PRIVATE_KEY=PRIVATE,
            WEBPUSH_CONTACT='mailto:test@example.test', ALLOWED_HOSTS=['testserver'])
FCM = 'https://fcm.googleapis.com/fcm/send/abc123'


def device_keys():
    """Clés d'un appareil fictif (ce que renvoie pushManager.subscribe())."""
    import os
    from cryptography.hazmat.primitives import serialization
    private = ec.generate_private_key(ec.SECP256R1())
    public = private.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return private, push.b64url_encode(public), push.b64url_encode(os.urandom(16))


class CryptoTests(TestCase):
    def test_encryption_matches_rfc8291_test_vector(self):
        server = ec.derive_private_key(int.from_bytes(push.b64url_decode(
            'yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw'), 'big'), ec.SECP256R1())
        body = push.encrypt(
            b'When I grow up, I want to be a watermelon',
            'BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4',
            'BTBZMqHH6r4Tts7J_aSIgg', salt=push.b64url_decode('DGv6ra1nlYgDCS1FRnbzlw'), server_private=server)
        self.assertEqual(push.b64url_encode(body), (
            'DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6Tlz'
            'AC8wEqKK6PBru3jl7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN'))

    @override_settings(**KEYS)
    def test_vapid_token_is_signed_with_the_configured_key(self):
        header = push.vapid_authorization(FCM, now=1_700_000_000)
        token = header.split('t=')[1].split(',')[0]
        self.assertTrue(header.endswith(f'k={PUBLIC}'))
        head, claims, signature = token.split('.')
        payload = json.loads(push.b64url_decode(claims))
        self.assertEqual(payload['aud'], 'https://fcm.googleapis.com')
        self.assertEqual(payload['sub'], 'mailto:test@example.test')
        raw = push.b64url_decode(signature)
        der = encode_dss_signature(int.from_bytes(raw[:32], 'big'), int.from_bytes(raw[32:], 'big'))
        public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), push.b64url_decode(PUBLIC))
        public.verify(der, f'{head}.{claims}'.encode(), ec.ECDSA(hashes.SHA256()))  # lève une erreur si invalide

    def test_only_browser_push_services_are_contacted(self):
        for url in (FCM, 'https://web.push.apple.com/abc', 'https://updates.push.services.mozilla.com/wpush/v2/x',
                    'https://db5p.notify.windows.com/w/?token=x'):
            self.assertTrue(push.endpoint_allowed(url), url)
        for url in ('http://fcm.googleapis.com/x', 'https://127.0.0.1/x', 'https://evil.example/fcm.googleapis.com',
                    'https://fcm.googleapis.com.evil.example/x', 'file:///etc/passwd'):
            self.assertFalse(push.endpoint_allowed(url), url)


@override_settings(**KEYS)
class SubscriptionAndDeliveryTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create(username='prof', email='p@t.test', role='teacher', first_name='Nadia')
        self.student = User.objects.create(username='omar', email='o@t.test', first_name='Omar')
        self.classmate = User.objects.create(username='salma', email='s@t.test', first_name='Salma')
        self.classroom = Classroom.objects.create(name='TC A', niveau='tronc_commun', teacher=self.teacher)
        self.classroom.add_member(self.student)
        self.classroom.add_member(self.classmate)
        self.device_private, self.p256dh, self.auth = device_keys()

    def login(self, user):
        session = self.client.session
        session['user_id'] = user.pk
        session.save()

    def subscribe(self, user, endpoint=FCM):
        self.login(user)
        return self.client.post(reverse('notifications:push_subscribe'), json.dumps({
            'endpoint': endpoint, 'keys': {'p256dh': self.p256dh, 'auth': self.auth}}), content_type='application/json')

    def test_subscribe_validates_endpoint_and_can_be_removed(self):
        self.assertEqual(self.subscribe(self.student, 'https://127.0.0.1:8000/hook').status_code, 400)
        self.assertEqual(self.subscribe(self.student).status_code, 200)
        self.assertEqual(PushSubscription.objects.get().user, self.student)
        self.client.post(reverse('notifications:push_unsubscribe'), json.dumps({'endpoint': FCM}),
                         content_type='application/json')
        self.assertFalse(PushSubscription.objects.exists())

    def test_private_message_reaches_the_students_phone_after_the_response(self):
        self.subscribe(self.student)
        conversation = PrivateConversation.objects.create(
            classroom=self.classroom, student=self.student, teacher=self.teacher)
        self.login(self.teacher)
        with mock.patch('notifications.push._post', return_value=201) as post:
            response = self.client.post(
                reverse('chat:api_private_send', args=[conversation.pk]),
                json.dumps({'body': 'Révisez la page 12 pour demain.'}), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(post.call_count, 1)
        subscription, body = post.call_args.args[:2]
        self.assertEqual(subscription.user, self.student)
        # Le téléphone peut déchiffrer le message : on joue le rôle de l'appareil.
        message = decrypt(body, self.device_private, self.auth)
        self.assertEqual(message['title'], 'Consultation — nouveau message')
        self.assertIn('Révisez la page 12', message['body'])
        self.assertEqual(message['url'], reverse('chat:private_room', args=[conversation.pk]))
        self.assertIsNotNone(PushSubscription.objects.get().last_success_at)

    def test_class_message_notifies_other_members_but_not_the_sender(self):
        for user in (self.student, self.classmate, self.teacher):
            self.device_private, self.p256dh, self.auth = device_keys()
            self.subscribe(user, endpoint=f'{FCM}-{user.pk}')
        ClassChatRoom.get_or_create_for(self.classroom)
        self.login(self.student)
        with mock.patch('notifications.push._post', return_value=201) as post:
            self.client.post(reverse('chat:api_send', args=[self.classroom.pk]),
                             json.dumps({'body': 'Quelqu’un a compris l’exercice 4 ?'}), content_type='application/json')
        recipients = {call.args[0].user for call in post.call_args_list}
        self.assertEqual(recipients, {self.classmate, self.teacher})

    def test_expired_device_is_forgotten(self):
        self.subscribe(self.student)
        with mock.patch('notifications.push._post', return_value=410):
            Notification.notify(self.student, 'Nouveau quiz assigné', 'Quiz « Logique »', type='quiz_assigned')
        self.assertFalse(PushSubscription.objects.exists())

    def test_muted_type_is_not_pushed(self):
        from .models import NotificationPreference
        self.subscribe(self.student)
        NotificationPreference.objects.create(user=self.student, values={'quiz_assigned': {'in_app': False, 'email': 'off'}})
        with mock.patch('notifications.push._post', return_value=201) as post:
            Notification.notify(self.student, 'Nouveau quiz assigné', 'x', type='quiz_assigned')
        post.assert_not_called()

    @override_settings(WEBPUSH_VAPID_PRIVATE_KEY='')
    def test_without_keys_nothing_is_sent_and_the_button_is_hidden(self):
        with mock.patch('notifications.push._post') as post:
            Notification.notify(self.student, 'Titre', 'x', type='system')
        post.assert_not_called()
        self.login(self.student)
        page = self.client.get(reverse('notifications:preferences'))
        self.assertContains(page, 'publicKey: ""')


def decrypt(body, device_private, auth):
    """Déchiffrement côté appareil (RFC 8291), pour vérifier ce que reçoit le téléphone."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    def hkdf(salt, ikm, info, length):
        return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(ikm)
    salt, idlen = body[:16], body[20]
    server_public = body[21:21 + idlen]
    ciphertext = body[21 + idlen:]
    ua_public = device_private.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    shared = device_private.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), server_public))
    ikm = hkdf(push.b64url_decode(auth), shared, b'WebPush: info\x00' + ua_public + server_public, 32)
    cek = hkdf(salt, ikm, b'Content-Encoding: aes128gcm\x00', 16)
    nonce = hkdf(salt, ikm, b'Content-Encoding: nonce\x00', 12)
    plain = AESGCM(cek).decrypt(nonce, ciphertext, None)
    return json.loads(plain.rstrip(b'\x02').decode('utf-8'))


class EmailAfterResponseTests(TestCase):
    """Un SMTP lent ou en panne ne bloque plus l'envoi d'un quiz à une classe."""

    def setUp(self):
        from education.models import Course, Lesson
        from quizzes.models import Choice, Question, Quiz
        self.teacher = User.objects.create(username='prof', email='p@t.test', role='teacher')
        self.students = [User.objects.create(username=f'el{i}', email=f'el{i}@t.test') for i in range(3)]
        self.classroom = Classroom.objects.create(name='1bac1', niveau='1ere_bac_sc', teacher=self.teacher)
        for student in self.students:
            self.classroom.add_member(student)
        lesson = Lesson.objects.create(
            course=Course.objects.create(name='Maths', niveau='1ere_bac_sc'), title='Fonctions', order=1)
        self.quiz = Quiz.objects.create(title='Généralités sur les fonctions numériques', lesson=lesson,
                                        created_by=self.teacher, status='draft', classroom=self.classroom)
        question = Question.objects.create(quiz=self.quiz, text='?')
        Choice.objects.create(question=question, text='a', is_correct=True)
        session = self.client.session
        session['user_id'] = self.teacher.pk
        session.save()

    def test_quiz_is_sent_even_if_smtp_fails_and_emails_wait_for_the_response(self):
        during_request = []

        def smtp_down(**kwargs):
            during_request.append(push._queue().in_request)
            raise ConnectionError('SMTP en panne')
        with self.assertLogs('notifications', level='WARNING'), \
                mock.patch('notifications.email_utils.send_notification_email', side_effect=smtp_down):
            response = self.client.post(reverse('quizzes:publish', args=[self.quiz.pk]))
        self.assertRedirects(response, reverse('quizzes:manage'), fetch_redirect_response=False)
        self.quiz.refresh_from_db()
        self.assertEqual(self.quiz.status, 'published')
        self.assertEqual(Notification.objects.filter(type='quiz_assigned').count(), 3)
        # Trois e-mails tentés, tous après la réponse (jamais pendant le clic).
        self.assertEqual(during_request, [False, False, False])


@override_settings(**KEYS)
class SendAndSharePushTests(TestCase):
    """Quiz envoyé à un élève précis, tableau partagé : le téléphone du destinataire sonne."""

    def setUp(self):
        self.teacher = User.objects.create(username='prof', email='p@t.test', role='teacher', first_name='Nadia')
        self.omar = User.objects.create(username='omar', email='o@t.test', first_name='Omar')
        self.salma = User.objects.create(username='salma', email='s@t.test', first_name='Salma')
        self.classroom = Classroom.objects.create(name='1bac1', niveau='1ere_bac_sc', teacher=self.teacher)
        self.classroom.add_member(self.omar)
        self.classroom.add_member(self.salma)
        self.devices = {}
        for user in (self.omar, self.salma):
            private, p256dh, auth = device_keys()
            self.devices[user.pk] = (private, auth)
            PushSubscription.objects.create(user=user, endpoint=f'{FCM}-{user.pk}', p256dh=p256dh, auth=auth)
        session = self.client.session
        session['user_id'] = self.teacher.pk
        session.save()

    def pushed(self, post):
        """{username: [messages déchiffrés]} pour chaque envoi au service de push."""
        result = {}
        for call in post.call_args_list:
            subscription, body = call.args[:2]
            private, auth = self.devices[subscription.user_id]
            result.setdefault(subscription.user.username, []).append(decrypt(body, private, auth))
        return result

    def test_quiz_sent_to_one_student_rings_only_that_phone(self):
        from education.models import Course, Lesson
        from quizzes.models import Quiz
        lesson = Lesson.objects.create(course=Course.objects.create(name='Maths', niveau='1ere_bac_sc'),
                                       title='Fonctions', order=1)
        quiz = Quiz.objects.create(title='Généralités sur les fonctions', lesson=lesson,
                                   created_by=self.teacher, status='draft')
        with mock.patch('notifications.push._post', return_value=201) as post:
            response = self.client.post(reverse('quizzes:assign'), {
                'quiz': quiz.pk, 'target': 'students', 'students': [self.omar.pk]})
        self.assertEqual(response.status_code, 302)
        pushed = self.pushed(post)
        self.assertEqual(list(pushed), ['omar'])
        self.assertEqual(pushed['omar'][0]['title'], 'Nouveau quiz assigné')
        self.assertIn('Généralités sur les fonctions', pushed['omar'][0]['body'])
        self.assertEqual(pushed['omar'][0]['url'], reverse('quizzes:detail', args=[quiz.pk]))

    def test_whiteboard_shared_with_the_class_rings_every_member(self):
        from types import SimpleNamespace
        from notifications.services import notify_whiteboard_share
        share = SimpleNamespace(pk=7, title='Correction exercice 3', classroom=self.classroom, teacher=self.teacher)
        with mock.patch('notifications.push._post', return_value=201) as post:
            notify_whiteboard_share(share)
        pushed = self.pushed(post)
        self.assertEqual(set(pushed), {'omar', 'salma'})
        self.assertEqual(pushed['salma'][0]['title'], 'Whiteboard partagé')

    def test_board_posted_in_a_consultation_rings_once_even_if_already_shared(self):
        from whiteboard.models import WhiteboardBoard
        conversation = PrivateConversation.objects.create(
            classroom=self.classroom, student=self.omar, teacher=self.teacher)
        board = WhiteboardBoard.objects.create(title='Révisions', created_by=self.teacher,
                                               content={'version': 1, 'objects': []})

        def share():
            with mock.patch('notifications.push._post', return_value=201) as post:
                response = self.client.post(reverse('whiteboard:share_to_conversation'), json.dumps({
                    'kind': 'consultation', 'conversation_id': conversation.pk, 'board_id': board.pk}),
                    content_type='application/json')
            self.assertEqual(response.status_code, 200, response.content)
            return self.pushed(post)

        first = share()  # Omar découvre le tableau : « Tableau partagé avec vous », une seule fois.
        self.assertEqual([m['title'] for m in first['omar']], ['Tableau partagé avec vous'])
        again = share()  # Il y avait déjà accès : il est prévenu du nouveau message.
        self.assertEqual([m['title'] for m in again['omar']], ['Consultation — nouveau message'])
        self.assertIn('Tableau en direct : Révisions', again['omar'][0]['body'])


@override_settings(**KEYS)
class PushDiagnosticsTests(TestCase):
    def setUp(self):
        self.student = User.objects.create(username='omar', email='o@t.test')
        _, p256dh, auth = device_keys()
        self.subscription = PushSubscription.objects.create(
            user=self.student, endpoint=FCM, p256dh=p256dh, auth=auth, user_agent='Mozilla/5.0 (Linux; Android 14)')
        session = self.client.session
        session['user_id'] = self.student.pk
        session.save()

    def test_button_sends_a_test_and_reports_success(self):
        with mock.patch('notifications.push._post', return_value=201) as post:
            data = self.client.post(reverse('notifications:push_test')).json()
        self.assertTrue(data['ok'])
        self.assertIn('1 appareil', data['message'])
        self.assertEqual(post.call_count, 1)  # envoyé tout de suite, pas après la réponse

    def test_button_explains_a_failure(self):
        import urllib.error
        with mock.patch('notifications.push._post', side_effect=urllib.error.URLError('Tunnel connection failed: 403')):
            data = self.client.post(reverse('notifications:push_test')).json()
        self.assertFalse(data['ok'])
        self.assertIn('Android / Chrome (Android)', data['message'])
        self.assertIn('Tunnel connection failed', data['message'])
        with mock.patch('notifications.push._post', return_value=403):
            data = self.client.post(reverse('notifications:push_test')).json()
        self.assertIn('clé VAPID a changé', data['message'])

    def test_command_lists_devices_and_sends(self):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        with mock.patch('notifications.push._post', return_value=201):
            call_command('push_check', send='omar', stdout=out)
        text = out.getvalue()
        self.assertIn('✓ Configurées', text)
        self.assertIn('omar', text)
        self.assertIn('accepté (201)', text)

    @override_settings(WEBPUSH_VAPID_PRIVATE_KEY='')
    def test_command_and_page_say_when_keys_are_missing(self):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        call_command('push_check', stdout=out)
        self.assertIn('generate_vapid_keys', out.getvalue())
        teacher = User.objects.create(username='prof', email='p@t.test', role='teacher')
        session = self.client.session
        session['user_id'] = teacher.pk
        session.save()
        self.assertContains(self.client.get(reverse('notifications:preferences')),
                            'Notifications sur le téléphone désactivées sur ce serveur')
