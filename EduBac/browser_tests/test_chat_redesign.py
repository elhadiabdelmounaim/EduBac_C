"""Interface de messagerie dans un vrai navigateur : disposition ordinateur et
smartphone, séparateurs de dates, lecteur vocal à forme d'onde, enregistrement.

Captures d'écran facultatives : CHAT_SCREENSHOT_DIR=/chemin python manage.py test ...
"""
import io
import math
import os
import shutil
import struct
import tempfile
import wave
from datetime import timedelta

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.files.base import ContentFile
from django.urls import reverse
from django.utils import timezone
from playwright.sync_api import expect, sync_playwright

from accounts.models import User
from chat.models import ChatMessage, ClassChatRoom, PrivateConversation, PrivateMessage
from chat.storage import PrivateChatStorage
from classrooms.models import Classroom, ClassroomMember

from .test_chat_moderation import PASSWORD, SingleThreadLiveServer


def wav_bytes(seconds=2.0, rate=8000):
    """Court son dont l'amplitude varie, pour une forme d'onde non plate."""
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        frames = bytearray()
        for i in range(int(seconds * rate)):
            t = i / rate
            envelope = 0.15 + 0.85 * abs(math.sin(t * 2.4))
            frames += struct.pack('<h', int(12000 * envelope * math.sin(2 * math.pi * 330 * t)))
        out.writeframes(bytes(frames))
    return buffer.getvalue()


class ChatRedesignBrowserTests(StaticLiveServerTestCase):
    server_thread_class = SingleThreadLiveServer

    def setUp(self):
        self.files = tempfile.TemporaryDirectory()
        self.addCleanup(self.files.cleanup)
        for model in (ChatMessage, PrivateMessage):
            field = model._meta.get_field('attachment')
            original = field.storage
            field.storage = PrivateChatStorage(location=self.files.name)
            self.addCleanup(setattr, field, 'storage', original)

        self.teacher = User.objects.create_user(
            username='ui-prof', email='ui-prof@example.test', password=PASSWORD,
            role='teacher', first_name='Nadia', last_name='Benali',
        )
        self.student = User.objects.create_user(
            username='ui-eleve', email='ui-eleve@example.test', password=PASSWORD,
            role='student', first_name='Omar', last_name='Alaoui',
        )
        self.classmate = User.objects.create_user(
            username='ui-camarade', email='ui-camarade@example.test', password=PASSWORD,
            role='student', first_name='Salma', last_name='Idrissi',
        )
        self.classroom = Classroom.objects.create(
            name='2BAC SM — Groupe A', niveau='tronc_commun', teacher=self.teacher,
        )
        for member in (self.student, self.classmate):
            ClassroomMember.objects.create(classroom=self.classroom, user=member)
        room = ClassChatRoom.get_or_create_for(self.classroom)
        yesterday = timezone.now() - timedelta(days=1)

        def say(sender, body='', when=None, **extra):
            message = ChatMessage.objects.create(room=room, sender=sender, body=body, **extra)
            if when:
                ChatMessage.objects.filter(pk=message.pk).update(created_at=when)
            return message

        say(self.teacher, 'Bonjour à tous ! Révisez le chapitre 2 pour demain.', yesterday)
        question = say(self.student, 'Je n’ai pas compris l’exercice 3 : pourquoi $x^2 \\geq 0$ ?')
        say(self.classmate, 'Moi non plus 😅')
        say(self.classmate, 'Surtout la dernière question.')
        say(self.teacher, 'Un carré est toujours positif. Je vous explique en vocal.', reply_to=question)
        voice = say(self.teacher, is_voice=True)
        voice.attachment.save('explication.wav', ContentFile(wav_bytes()), save=True)
        say(self.student, 'Merci madame, c’est clair ! Voir https://edubac.example/cours', is_pinned=True)

        self.consultation = PrivateConversation.objects.create(
            classroom=self.classroom, student=self.student, teacher=self.teacher,
        )
        sent = PrivateMessage.objects.create(
            conversation=self.consultation, sender=self.student, body='Bonjour madame, une question sur le devoir.',
        )
        PrivateMessage.objects.filter(pk=sent.pk).update(read_at=timezone.now())
        PrivateMessage.objects.create(
            conversation=self.consultation, sender=self.teacher, body='Bien sûr, je vous écoute.',
        )

    def login(self, page, user):
        page.goto(self.live_server_url + reverse('accounts:login'))
        page.locator('input[name="username"]').fill(user.username)
        page.locator('input[name="password"]').fill(PASSWORD)
        page.locator('form button[type="submit"]').first.click()
        page.wait_for_url(lambda url: '/connexion/' not in url)

    def shot(self, page, name):
        folder = os.environ.get('CHAT_SCREENSHOT_DIR')
        if folder:
            page.screenshot(path=os.path.join(folder, f'{name}.png'))

    def assert_no_horizontal_scroll(self, page):
        overflow = page.evaluate('document.documentElement.scrollWidth - window.innerWidth')
        self.assertLessEqual(overflow, 0, 'la page ne doit pas défiler horizontalement')

    def launch(self, pw):
        return pw.chromium.launch(
            executable_path=os.environ.get('CHROMIUM_EXECUTABLE') or shutil.which('chromium'),
            headless=True,
            args=['--no-sandbox', '--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream',
                  '--autoplay-policy=no-user-gesture-required'],
        )

    def test_desktop_layout_dates_waveform_player_and_composer(self):
        with sync_playwright() as pw:
            browser = self.launch(pw)
            try:
                errors = []
                page = browser.new_page(viewport={'width': 1366, 'height': 820})
                page.on('pageerror', lambda error: errors.append(str(error)))
                self.login(page, self.teacher)
                page.goto(self.live_server_url + reverse('chat:home'))
                expect(page.locator('.chat-thread')).to_have_count(2)
                expect(page.locator('.chat-welcome')).to_be_visible()
                self.shot(page, 'desktop-home')

                page.locator('.chat-thread[data-kind="class"]').click()
                expect(page.locator('.chat-sidebar')).to_be_visible()
                expect(page.locator('.chat-thread.is-active')).to_have_count(1)
                expect(page.locator('.chat-back-btn')).to_be_hidden()
                expect(page.locator('.chat-day-sep')).to_have_text(['Hier', 'Aujourd’hui'])
                expect(page.locator('.chat-bubble-row.is-continuation')).to_have_count(2)
                expect(page.locator('.chat-pinned-bar')).to_be_visible()
                expect(page.locator('a.chat-link')).to_have_attribute('href', 'https://edubac.example/cours')

                player = page.locator('.chat-voice').first
                expect(player.locator('.chat-voice-bar')).to_have_count(36)
                expect(player).not_to_have_class('is-estimated', timeout=10000)
                expect(player.locator('.chat-voice-duration')).to_have_text('0:02')
                player.locator('.chat-voice-play').click()
                expect(player).to_have_attribute('data-state', 'playing')
                expect(player.locator('.chat-voice-play')).to_have_attribute('aria-label', 'Mettre en pause')
                player.locator('.chat-voice-play').click()
                expect(player).to_have_attribute('data-state', 'paused')
                box = player.locator('.chat-voice-wave').bounding_box()
                page.mouse.click(box['x'] + box['width'] * 0.5, box['y'] + box['height'] / 2)
                expect(player).to_have_class('chat-voice is-started')
                self.assertGreater(player.locator('.chat-voice-bar.is-played').count(), 12)
                player.locator('.chat-voice-speed').click()
                expect(player.locator('.chat-voice-speed')).to_have_text('1,5×')

                send = page.locator('#chatForm .chat-send-btn')
                mic = page.locator('#chatVoiceBtn')
                expect(mic).to_be_visible()
                expect(send).to_be_hidden()
                page.locator('#chatInput').fill('Bonne révision à tous')
                expect(send).to_be_visible()
                expect(mic).to_be_hidden()
                self.shot(page, 'desktop-room')
                page.locator('#chatInput').press('Enter')
                expect(page.locator('.chat-bubble-row.mine').last).to_contain_text('Bonne révision à tous')
                expect(mic).to_be_visible()
                self.assert_no_horizontal_scroll(page)

                page.goto(self.live_server_url + reverse('chat:private_room', args=[self.consultation.pk]))
                expect(page.locator('.chat-bubble-row.mine')).to_have_count(1)
                expect(page.locator('.chat-thread.is-active')).to_have_attribute(
                    'data-thread', f'consultation-{self.consultation.pk}',
                )
                page.locator('#privateAttachToggle').click()
                expect(page.locator('#privateAttachMenu')).to_be_visible()
                self.shot(page, 'desktop-private')
                page.keyboard.press('Escape')

                page.evaluate("localStorage.setItem('edubac-theme', 'dark')")
                page.goto(self.live_server_url + reverse('chat:room', args=[self.classroom.pk]))
                expect(page.locator('.chat-voice').first).to_be_visible()
                self.shot(page, 'desktop-room-dark')
                self.assertEqual(errors, [])
            finally:
                browser.close()

    def test_phone_list_first_then_full_screen_conversation_and_voice_recording(self):
        with sync_playwright() as pw:
            browser = self.launch(pw)
            try:
                errors = []
                context = browser.new_context(
                    viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True,
                    device_scale_factor=2,
                )
                page = context.new_page()
                page.on('pageerror', lambda error: errors.append(str(error)))
                self.login(page, self.student)
                page.goto(self.live_server_url + reverse('chat:home'))
                expect(page.locator('.chat-sidebar')).to_be_visible()
                expect(page.locator('.chat-welcome')).to_be_hidden()
                self.assert_no_horizontal_scroll(page)
                page.locator('.chat-chip[data-filter="groups"]').click()
                expect(page.locator('.chat-thread:visible')).to_have_count(1)
                self.shot(page, 'phone-list')

                page.locator('.chat-thread[data-kind="class"]').click()
                expect(page.locator('.chat-sidebar')).to_be_hidden()
                expect(page.locator('.chat-back-btn')).to_be_visible()
                expect(page.locator('.chat-voice')).to_have_count(1)
                self.assert_no_horizontal_scroll(page)
                width = page.viewport_size['width']
                for box in page.locator('.chat-bubble').evaluate_all(
                    'nodes => nodes.map(n => n.getBoundingClientRect().right)'
                ):
                    self.assertLessEqual(box, width)
                self.assertGreaterEqual(page.locator('#chatVoiceBtn').bounding_box()['height'], 44)
                self.shot(page, 'phone-room')

                # Enregistrer, écouter, recommencer, puis envoyer.
                page.locator('#chatVoiceBtn').click()
                expect(page.locator('#chatVoiceRec')).to_be_visible()
                expect(page.locator('#chatForm')).to_be_hidden()
                page.wait_for_timeout(1300)
                self.shot(page, 'phone-recording')
                page.locator('#chatVoiceStop').click()
                expect(page.locator('#chatVoicePreview')).to_be_visible()
                expect(page.locator('#chatVoicePreviewWave .chat-voice-bar')).to_have_count(40)
                self.shot(page, 'phone-preview')
                page.locator('#chatVoiceRestart').click()
                expect(page.locator('#chatVoiceRec')).to_be_visible()
                page.wait_for_timeout(1200)
                page.locator('#chatVoiceRecSend').click()
                expect(page.locator('.chat-voice')).to_have_count(2, timeout=10000)
                expect(page.locator('#chatForm')).to_be_visible()
                self.assert_no_horizontal_scroll(page)

                page.locator('.chat-back-btn').click()
                page.wait_for_url(lambda url: url.rstrip('/').endswith('/chat'))
                expect(page.locator('.chat-sidebar')).to_be_visible()
                self.assertEqual(errors, [])
            finally:
                browser.close()
        voice = ChatMessage.objects.filter(sender=self.student, is_voice=True)
        self.assertEqual(voice.count(), 1, 'un seul message vocal envoyé (l’essai recommencé est jeté)')
