"""Répondre à un message précis dans une consultation, dans un vrai navigateur : bouton
« Répondre », bande au-dessus de la saisie, citation dans la bulle envoyée, clic vers l'original."""
import os
import shutil

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from accounts.models import User
from chat.models import PrivateConversation, PrivateMessage
from classrooms.models import Classroom, ClassroomMember

from .test_chat_moderation import PASSWORD, SingleThreadLiveServer


class ChatReponsesBrowserTests(StaticLiveServerTestCase):
    server_thread_class = SingleThreadLiveServer

    def setUp(self):
        self.teacher = User.objects.create_user(
            username='rep-prof', email='rep-prof@example.test', password=PASSWORD,
            role='teacher', first_name='Nadia', last_name='Benali',
        )
        self.student = User.objects.create_user(
            username='rep-eleve', email='rep-eleve@example.test', password=PASSWORD,
            role='student', first_name='Omar', last_name='Alaoui',
        )
        classroom = Classroom.objects.create(name='1BAC A', niveau='tronc_commun', teacher=self.teacher)
        ClassroomMember.objects.create(classroom=classroom, user=self.student)
        self.consultation = PrivateConversation.objects.create(
            classroom=classroom, student=self.student, teacher=self.teacher,
        )
        self.question = PrivateMessage.objects.create(
            conversation=self.consultation, sender=self.student, body='Pourquoi $x^2 \\geq 0$ ?',
        )

    def login(self, page, user):
        page.goto(self.live_server_url + reverse('accounts:login'))
        page.locator('input[name="username"]').fill(user.username)
        page.locator('input[name="password"]').fill(PASSWORD)
        page.locator('form button[type="submit"]').first.click()
        page.wait_for_url(lambda url: '/connexion/' not in url)

    def launch(self, pw):
        return pw.chromium.launch(
            executable_path=os.environ.get('CHROMIUM_EXECUTABLE') or shutil.which('chromium'),
            headless=True, args=['--no-sandbox'],
        )

    def repondre(self, page, tap=False):
        page.goto(self.live_server_url + reverse('chat:private_room', args=[self.consultation.pk]))
        original = page.locator(f'#private-message-{self.question.pk}')
        expect(original).to_be_visible()
        if tap:
            original.locator('.chat-message-text').tap()
            original.locator('.chat-act-reply').tap()
        else:
            original.locator('.chat-bubble').hover()
            original.locator('.chat-act-reply').click()
        bande = page.locator('#privateReplyBar')
        expect(bande).to_be_visible()
        expect(page.locator('#privateReplyName')).to_have_text('Omar Alaoui')
        page.locator('#chatInput').fill('Un carré est toujours positif.')
        page.locator('#chatForm .chat-send-btn').click()
        envoye = page.locator('.chat-bubble-row.mine').last
        expect(envoye.locator('.chat-reply-quote strong')).to_have_text('Omar Alaoui')
        expect(envoye.locator('.chat-reply-quote .katex')).to_have_count(1)    # formule rendue dans la citation
        expect(bande).to_be_hidden()
        envoye.locator('.chat-reply-quote').click()
        expect(original).to_be_in_viewport()

    def test_ordinateur(self):
        with sync_playwright() as pw:
            browser = self.launch(pw)
            try:
                errors = []
                page = browser.new_page(viewport={'width': 1280, 'height': 820})
                page.on('pageerror', lambda error: errors.append(str(error)))
                self.login(page, self.teacher)
                self.repondre(page)
                self.assertEqual(errors, [])
            finally:
                browser.close()
        self.assertEqual(PrivateMessage.objects.latest('pk').reply_to_id, self.question.pk)

    def test_telephone(self):
        with sync_playwright() as pw:
            browser = self.launch(pw)
            try:
                context = browser.new_context(viewport={'width': 390, 'height': 800}, has_touch=True, is_mobile=True)
                page = context.new_page()
                self.login(page, self.teacher)
                self.repondre(page, tap=True)
                overflow = page.evaluate('document.documentElement.scrollWidth - window.innerWidth')
                self.assertLessEqual(overflow, 0)
            finally:
                browser.close()
