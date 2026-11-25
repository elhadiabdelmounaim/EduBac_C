"""Réactions dans un vrai navigateur : l'élève réagit ✅ / ❓ depuis la palette, le compteur
s'affiche, la même réaction la retire ; le professeur voit qui n'a pas compris. Ordinateur et
téléphone (toucher la bulle affiche les actions)."""
import os
import shutil

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from accounts.models import User
from chat.models import ChatMessage, ClassChatRoom, MessageReaction
from classrooms.models import Classroom, ClassroomMember

from .test_chat_moderation import PASSWORD, SingleThreadLiveServer


class ChatReactionsBrowserTests(StaticLiveServerTestCase):
    server_thread_class = SingleThreadLiveServer

    def setUp(self):
        self.teacher = User.objects.create_user(
            username='r-prof', email='r-prof@example.test', password=PASSWORD,
            role='teacher', first_name='Nadia', last_name='Benali',
        )
        self.student = User.objects.create_user(
            username='r-eleve', email='r-eleve@example.test', password=PASSWORD,
            role='student', first_name='Omar', last_name='Alaoui',
        )
        self.classroom = Classroom.objects.create(name='1BAC A', niveau='tronc_commun', teacher=self.teacher)
        ClassroomMember.objects.create(classroom=self.classroom, user=self.student)
        room = ClassChatRoom.get_or_create_for(self.classroom)
        self.message = ChatMessage.objects.create(
            room=room, sender=self.teacher, body='Le produit scalaire : $\\vec u\\cdot\\vec v=xx\'+yy\'$.',
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

    def bulle(self, page):
        return page.locator(f'#msg-{self.message.pk}')

    def test_eleve_reagit_puis_professeur_voit_qui_n_a_pas_compris(self):
        with sync_playwright() as pw:
            browser = self.launch(pw)
            try:
                errors = []
                page = browser.new_page(viewport={'width': 1280, 'height': 820})
                page.on('pageerror', lambda error: errors.append(str(error)))
                self.login(page, self.student)
                page.goto(self.live_server_url + reverse('chat:room', args=[self.classroom.pk]))
                bulle = self.bulle(page)
                expect(bulle).to_be_visible()
                bulle.locator('.chat-bubble').hover()
                bulle.locator('.chat-act-react').click()
                palette = page.locator('.chat-reaction-picker')
                expect(palette).to_be_visible()
                expect(palette.locator('.chat-reaction-choice')).to_have_count(6)
                palette.locator('[data-emoji="❓"]').click()
                pastille = self.bulle(page).locator('.chat-reaction[data-emoji="❓"]')
                expect(pastille).to_have_text('❓ 1')
                expect(pastille).to_have_attribute('aria-pressed', 'true')
                # L'élève ne voit pas les noms.
                expect(self.bulle(page).locator('.chat-reaction-who')).to_have_count(0)

                # Le professeur voit qui n'a pas compris.
                prof = browser.new_page(viewport={'width': 1280, 'height': 820})
                self.login(prof, self.teacher)
                prof.goto(self.live_server_url + reverse('chat:room', args=[self.classroom.pk]))
                expect(self.bulle(prof).locator('.chat-reaction-who')).to_have_text('❓ Pas compris : Omar Alaoui')

                # Retirer sa réaction : appuyer de nouveau sur la pastille.
                self.bulle(page).locator('.chat-reaction[data-emoji="❓"]').click()
                expect(self.bulle(page).locator('.chat-reaction')).to_have_count(0)
                self.assertEqual(errors, [])
            finally:
                browser.close()
        self.assertFalse(MessageReaction.objects.exists())   # (base consultée hors du navigateur)

    def test_telephone_toucher_la_bulle_puis_reagir(self):
        with sync_playwright() as pw:
            browser = self.launch(pw)
            try:
                context = browser.new_context(viewport={'width': 390, 'height': 800}, has_touch=True, is_mobile=True)
                page = context.new_page()
                self.login(page, self.student)
                page.goto(self.live_server_url + reverse('chat:room', args=[self.classroom.pk]))
                bulle = self.bulle(page)
                bulle.locator('.chat-message-text').tap()
                bulle.locator('.chat-act-react').tap()
                palette = page.locator('.chat-reaction-picker')
                expect(palette).to_be_visible()
                boite = palette.bounding_box()
                self.assertGreaterEqual(boite['x'], 0)
                self.assertLessEqual(boite['x'] + boite['width'], 390)
                palette.locator('[data-emoji="✅"]').tap()
                expect(self.bulle(page).locator('.chat-reaction[data-emoji="✅"]')).to_have_text('✅ 1')
                overflow = page.evaluate('document.documentElement.scrollWidth - window.innerWidth')
                self.assertLessEqual(overflow, 0)
            finally:
                browser.close()
        self.assertEqual(MessageReaction.objects.get().emoji, '✅')
