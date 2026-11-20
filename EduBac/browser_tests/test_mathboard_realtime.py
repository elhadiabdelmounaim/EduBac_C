"""Phase 9 — production : serveur ASGI réel (Daphne) avec WebSocket, deux navigateurs.

Vérifie la diffusion instantanée, les curseurs distants et la reconnexion
automatique. Couche de canaux : Redis si REDIS_URL est défini, sinon mémoire.
"""
import os
import shutil
import unittest

from channels.testing import ChannelsLiveServerTestCase
from django.db import connection
from django.test import override_settings
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from accounts.models import User
from classrooms.models import Classroom
from mathboard.models import WhiteboardDocument, WhiteboardPage

from .test_chat_moderation import PASSWORD


@override_settings(MATHBOARD_WEBSOCKET=True)
class MathboardRealtimeTests(ChannelsLiveServerTestCase):
    serve_static = True

    @classmethod
    def setUpClass(cls):
        if connection.vendor == 'sqlite':
            raise unittest.SkipTest('Test de production : lancer avec PostgreSQL (DATABASE_URL) et Redis (REDIS_URL).')
        super().setUpClass()

    def setUp(self):
        self.teacher = User.objects.create_user(username='prof-rt', email='prt@example.test', password=PASSWORD,
                                                role='teacher', first_name='Karim')
        self.student = User.objects.create_user(username='eleve-rt', email='ert@example.test', password=PASSWORD,
                                                role='student', first_name='Salma')
        classroom = Classroom.objects.create(name='2bac', niveau='2bac_pc', teacher=self.teacher)
        classroom.add_member(self.student)
        self.document = WhiteboardDocument.objects.create(title='Direct', owner=self.teacher, classroom=classroom,
                                                          students_can_edit=True)
        WhiteboardPage.objects.create(document=self.document, uid='page-1', position=0)

    def open(self, browser, user):
        page = browser.new_context(viewport={'width': 1280, 'height': 820}).new_page()
        page.goto(self.live_server_url + reverse('accounts:login'))
        page.locator('input[name="username"]').fill(user.username)
        page.locator('input[name="password"]').fill(PASSWORD)
        page.locator('form button[type="submit"]').first.click()
        page.wait_for_url(lambda url: '/connexion/' not in url)
        page.goto(self.live_server_url + reverse('mathboard:editor', args=[self.document.pk]))
        page.wait_for_function('window.MB && MB.board && MB.board.sync && MB.board.sync.socketOpen', timeout=15000)
        return page

    def test_live_updates_cursors_and_reconnection(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=os.environ.get('CHROMIUM_EXECUTABLE') or shutil.which('chromium'),
                                         headless=True, args=['--no-sandbox'])
            teacher, student = self.open(browser, self.teacher), self.open(browser, self.student)
            expect(teacher.locator('#mbStatus')).to_contain_text('en direct')
            # Interrogation HTTP ralentie à 20 s quand WebSocket est ouvert : une mise à jour en
            # moins de 3 s prouve la diffusion par WebSocket.
            teacher.click('[data-tool="rect"]')
            box = teacher.locator('#mbCanvasHost').bounding_box()
            teacher.mouse.move(box['x'] + 100, box['y'] + 100); teacher.mouse.down()
            teacher.mouse.move(box['x'] + 220, box['y'] + 190, steps=5); teacher.mouse.up()
            student.wait_for_function('Object.keys(MB.board.byId).length === 1', timeout=3000)
            # Curseur du professeur affiché chez l'élève, avec son nom.
            teacher.mouse.move(box['x'] + 400, box['y'] + 300, steps=3)
            expect(student.locator('.mb-cursor')).to_contain_text('Karim', timeout=3000)
            # Présence en direct.
            student.wait_for_function("document.querySelectorAll('#mbPresence .mb-avatar').length === 2", timeout=5000)
            # Coupure du WebSocket côté élève : reconnexion automatique puis rattrapage.
            student.evaluate('MB.board.sync.socket.close()')
            teacher.click('[data-tool="ellipse"]')
            teacher.mouse.move(box['x'] + 300, box['y'] + 100); teacher.mouse.down()
            teacher.mouse.move(box['x'] + 400, box['y'] + 180, steps=5); teacher.mouse.up()
            student.wait_for_function('MB.board.sync.socketOpen', timeout=10000)
            student.wait_for_function('Object.keys(MB.board.byId).length === 2', timeout=10000)
            # L'élève écrit à son tour : le professeur le voit aussitôt.
            student.click('[data-tool="pen"]')
            sbox = student.locator('#mbCanvasHost').bounding_box()
            student.mouse.move(sbox['x'] + 120, sbox['y'] + 320); student.mouse.down()
            student.mouse.move(sbox['x'] + 260, sbox['y'] + 360, steps=6); student.mouse.up()
            teacher.wait_for_function('Object.keys(MB.board.byId).length === 3', timeout=3000)
            browser.close()
