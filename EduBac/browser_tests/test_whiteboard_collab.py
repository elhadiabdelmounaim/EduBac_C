"""Tableau collaboratif avec trois comptes réels (enseignant + deux élèves).

Le serveur de test est WSGI, comme PythonAnywhere : aucune WebSocket, la
synchronisation passe donc par le repli HTTP. Captures facultatives :
CHAT_SCREENSHOT_DIR=/dossier.
"""
import os
import shutil

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from accounts.models import User
from classrooms.models import Classroom
from whiteboard.models import WhiteboardBoard

from .test_chat_moderation import PASSWORD, SingleThreadLiveServer

COUNT = 'window.EduBacBoard.getObjects().length'


class WhiteboardCollaborationBrowserTests(StaticLiveServerTestCase):
    server_thread_class = SingleThreadLiveServer

    def setUp(self):
        self.teacher = User.objects.create_user(
            username='wb-prof', email='wb-prof@example.test', password=PASSWORD,
            role='teacher', first_name='Nadia', last_name='Benali')
        self.omar = User.objects.create_user(
            username='wb-omar', email='wb-omar@example.test', password=PASSWORD,
            role='student', first_name='Omar', last_name='Alaoui')
        self.salma = User.objects.create_user(
            username='wb-salma', email='wb-salma@example.test', password=PASSWORD,
            role='student', first_name='Salma', last_name='Idrissi')
        classroom = Classroom.objects.create(name='2BAC SM', niveau='tronc_commun', teacher=self.teacher)
        classroom.add_member(self.omar)
        classroom.add_member(self.salma)
        self.board = WhiteboardBoard.objects.create(
            title='Exercice 3', created_by=self.teacher, classroom=classroom,
            content={'version': 1, 'objects': []})

    def shot(self, page, name):
        folder = os.environ.get('CHAT_SCREENSHOT_DIR')
        if folder:
            page.screenshot(path=os.path.join(folder, f'wb-{name}.png'))

    def open(self, browser, user, width=1366):
        context = browser.new_context(viewport={'width': width, 'height': 860})
        page = context.new_page()
        page.on('pageerror', lambda error: self.errors.append(f'{user.username}: {error}'))
        page.goto(self.live_server_url + reverse('accounts:login'))
        page.locator('input[name="username"]').fill(user.username)
        page.locator('input[name="password"]').fill(PASSWORD)
        page.locator('form button[type="submit"]').first.click()
        page.wait_for_url(lambda url: '/connexion/' not in url)
        page.goto(self.live_server_url + reverse('whiteboard:room', args=[self.board.pk]))
        expect(page.locator('#wbConnection')).to_have_text('Synchronisé', timeout=10000)
        return context, page

    def draw(self, page, fx, fy):
        """Trace un trait court à une position relative du tableau (0..1)."""
        box = page.locator('#wbCanvas').bounding_box()
        x0, y0 = box['x'] + box['width'] * fx, box['y'] + box['height'] * fy
        page.mouse.move(x0, y0)
        page.mouse.down()
        for step in range(1, 6):
            page.mouse.move(x0 + box['width'] * 0.08 * step / 5, y0 + box['height'] * 0.04 * step / 5)
        page.mouse.up()

    def wait_count(self, page, expected):
        page.wait_for_function(f'{COUNT} === {expected}', timeout=10000)

    def test_three_accounts_collaborate_with_permissions(self):
        self.errors = []
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                executable_path=os.environ.get('CHROMIUM_EXECUTABLE') or shutil.which('chromium'),
                headless=True, args=['--no-sandbox'])
            try:
                _, teacher = self.open(browser, self.teacher)
                omar_ctx, omar = self.open(browser, self.omar)
                _, salma = self.open(browser, self.salma, width=420)

                # Élèves : lecture seule, sans outils, avec la main levée possible.
                expect(omar.locator('#wbToolbar')).to_be_hidden()
                expect(omar.locator('#wbHandBtn')).to_be_visible()
                omar.locator('#wbHandBtn').click()
                expect(omar.locator('#wbHandBtn')).to_have_attribute('aria-pressed', 'true')
                expect(teacher.locator('#wbHandCount')).to_have_text('1', timeout=10000)
                omar_row = teacher.locator('#wbPeopleList li', has_text='Omar Alaoui')
                expect(omar_row.locator('.wb-person-hand')).to_be_visible()

                # Le dessin de l'enseignant arrive chez les deux élèves.
                self.draw(teacher, 0.15, 0.2)
                self.wait_count(omar, 1)
                self.wait_count(salma, 1)

                # Autorisation individuelle : seul Omar reçoit les outils.
                omar_row.get_by_role('button', name='Autoriser').click()
                expect(omar.locator('#wbToolbar')).to_be_visible(timeout=10000)
                expect(salma.locator('#wbToolbar')).to_be_hidden()
                expect(omar_row.locator('.wb-person-hand')).to_have_count(0)

                # Dessins simultanés : rien n'est écrasé.
                self.draw(omar, 0.2, 0.5)
                self.draw(teacher, 0.55, 0.5)
                for page in (teacher, omar, salma):
                    self.wait_count(page, 3)

                # Curseur d'Omar visible chez l'enseignant, avec son nom.
                box = omar.locator('#wbCanvas').bounding_box()
                omar.mouse.move(box['x'] + box['width'] * 0.6, box['y'] + box['height'] * 0.3)
                omar.mouse.move(box['x'] + box['width'] * 0.62, box['y'] + box['height'] * 0.32)
                expect(teacher.locator('.wb-cursor', has_text='Omar Alaoui')).to_be_visible(timeout=10000)
                self.shot(teacher, 'teacher')
                self.shot(omar, 'student-allowed')

                # Omar ne peut pas modifier le trait de l'enseignant (refus serveur, rétabli).
                rejected = omar.evaluate("""() => {
                    const objects = window.EduBacBoard._collab.objects();
                    const teacherStroke = objects.find(o => o.by !== %d);
                    teacherStroke.color = '#ff0000';
                    window.EduBacBoard._collab.setObjects(objects.slice());
                    window.EduBacCollab.syncNow();
                    return teacherStroke.id;
                }""" % self.omar.pk)
                omar.wait_for_function(
                    "id => window.EduBacBoard.getObjects().find(o => o.id === id).color !== '#ff0000'",
                    arg=rejected, timeout=10000)
                expect(omar.locator('#wbToast')).to_contain_text('propres éléments')

                # La main à Salma, puis reprise par l'enseignant.
                salma_row = teacher.locator('#wbPeopleList li', has_text='Salma Idrissi')
                salma_row.get_by_role('button', name='Donner la main').click()
                expect(salma.locator('#wbControlBanner')).to_contain_text('C’est à vous', timeout=10000)
                expect(salma.locator('#wbToolbar')).to_be_visible()
                expect(teacher.locator('#wbControlBanner')).to_contain_text('Salma Idrissi a la main')
                self.shot(salma, 'student-control-phone')
                teacher.locator('#wbControlBanner button').click()
                expect(salma.locator('#wbToolbar')).to_be_hidden(timeout=10000)

                # Hors ligne : le trait d'Omar est conservé puis envoyé à la reconnexion.
                omar_ctx.set_offline(True)
                self.draw(omar, 0.2, 0.75)
                expect(omar.locator('#wbConnection')).to_have_text('Hors ligne', timeout=10000)
                omar_ctx.set_offline(False)
                omar.evaluate('window.EduBacCollab.syncNow()')
                self.wait_count(teacher, 4)
                self.wait_count(salma, 4)

                # Verrou : plus aucun outil pour l'élève autorisé.
                teacher.locator('#wbPermForm input[name="is_locked"]').check(force=True)
                expect(omar.locator('#wbToolbar')).to_be_hidden(timeout=10000)
                expect(omar.locator('#wbMyStatus')).to_contain_text('verrouillé')

                # Partage limité à Omar : Salma perd l'accès.
                teacher.locator('#wbLiveShare').click()
                dialog = teacher.locator('#wbLiveShareDialog')
                dialog.locator('input[value="selected"]').check()
                dialog.locator('#wbLiveStudents label', has_text='Salma Idrissi').locator('input').uncheck()
                dialog.locator('#wbLiveStudents label', has_text='Omar Alaoui').locator('input').check()
                dialog.get_by_role('button', name='Partager et prévenir').click()
                expect(dialog).to_be_hidden()
                response = salma.goto(self.live_server_url + reverse('whiteboard:room', args=[self.board.pk]))
                self.assertEqual(response.status, 403)
                self.assertEqual(self.errors, [])
            finally:
                browser.close()
        self.board.refresh_from_db()
        self.assertEqual(len(self.board.content['objects']), 4)
        self.assertEqual(
            sorted({o['by'] for o in self.board.content['objects']}), sorted({self.teacher.pk, self.omar.pk}))
