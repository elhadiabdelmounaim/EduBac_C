"""Tableau mathématique dans Chrome : travail à rendre et correction, mode
présentation, participation, texte arabe, stylet (pression, paume), images en
fichiers, ouverture hors connexion, conversion d'un ancien tableau."""
import os
import shutil
import tempfile
import uuid

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from accounts.models import User
from classrooms.models import Classroom
from mathboard.models import WhiteboardDocument, WhiteboardPage
from whiteboard.models import WhiteboardBoard

from .test_chat_moderation import PASSWORD, SingleThreadLiveServer


class MathboardClassBrowserTests(StaticLiveServerTestCase):
    server_thread_class = SingleThreadLiveServer

    def setUp(self):
        self.teacher = User.objects.create_user(username='prof-classe', email='pc@example.test', password=PASSWORD,
                                                role='teacher', first_name='Karim', last_name='Prof')
        self.student = User.objects.create_user(username='eleve-classe', email='ec@example.test', password=PASSWORD,
                                                role='student', first_name='Salma', last_name='Élève',
                                                recovery_code_hash='code-deja-note')
        self.classroom = Classroom.objects.create(name='1bac1', niveau='1bac_sm', teacher=self.teacher)
        self.classroom.add_member(self.student)
        self.document = WhiteboardDocument.objects.create(title='Séance', owner=self.teacher, classroom=self.classroom)
        WhiteboardPage.objects.create(document=self.document, uid='page-1', position=0, background='grid')
        self.errors = []

    # ---------- outils ----------
    def launch(self, pw):
        return pw.chromium.launch(executable_path=os.environ.get('CHROMIUM_EXECUTABLE') or shutil.which('chromium'),
                                  headless=True, args=['--no-sandbox'])

    def context(self, browser, user, **options):
        context = browser.new_context(**{'viewport': {'width': 1280, 'height': 820}, **options})
        page = context.new_page()
        page.on('pageerror', lambda e: self.errors.append(str(e)))
        page.on('console', lambda m: self.errors.append(m.text) if m.type == 'error' else None)
        page.on('dialog', lambda d: d.accept())
        page.goto(self.live_server_url + reverse('accounts:login'))
        page.locator('input[name="username"]').fill(user.username)
        page.locator('input[name="password"]').fill(PASSWORD)
        page.locator('form button[type="submit"]').first.click()
        page.wait_for_url(lambda url: '/connexion/' not in url)
        return context, page

    def open(self, page, document_id):
        page.goto(self.live_server_url + reverse('mathboard:editor', args=[document_id]))
        page.wait_for_function('window.MB && MB.board && MB.board.pages.length > 0 && MB.Work')
        page.wait_for_function("document.getElementById('mbStatus').dataset.state === 'saved'", timeout=15000)

    def wait_saved(self, page):
        page.wait_for_function("document.getElementById('mbStatus').dataset.state === 'saved' && MB.board.sync.pending().length === 0",
                               timeout=15000)

    def state(self, page, document_id):
        return page.evaluate("async (u) => (await fetch(u, {credentials: 'same-origin'})).json()",
                             reverse('mathboard:api_state', args=[document_id]))

    def drag(self, page, x1, y1, x2, y2):
        box = page.locator('#mbCanvasHost').bounding_box()
        page.mouse.move(box['x'] + x1, box['y'] + y1)
        page.mouse.down()
        page.mouse.move(box['x'] + (x1 + x2) / 2, box['y'] + (y1 + y2) / 2, steps=4)
        page.mouse.move(box['x'] + x2, box['y'] + y2, steps=4)
        page.mouse.up()

    # ---------- Préparer sans partager ----------
    def test_prepare_for_class_then_share(self):
        with sync_playwright() as pw:
            browser = self.launch(pw)
            _, page = self.context(browser, self.teacher)
            page.goto(self.live_server_url + reverse('mathboard:list'))
            expect(page.locator('#mbNewNow')).to_be_disabled()
            page.locator('#mbNewName').fill('Séance préparée')
            page.locator('#mbNewClass').select_option(str(self.classroom.pk))
            expect(page.locator('#mbNewNow')).to_be_enabled()
            expect(page.locator('#mbNewLater')).to_be_checked()
            page.locator('#mbNewForm button[type="submit"]').click()
            page.wait_for_url('**/tableau-maths/*/')
            page.wait_for_function('window.MB && MB.board && MB.Work')
            banner = page.locator('#mbWorkBanner')
            expect(banner).to_contain_text('les élèves ne le voient pas encore')
            document_id = int(page.url.rstrip('/').split('/')[-1])
            # Dans « Partager », la case reflète l'état.
            page.locator('#mbShareBtn').click()
            expect(page.locator('#mbShareVisible')).not_to_be_checked()
            page.locator('#mbShareDialog button[value="close"]').click()
            page.locator('#mbPublishBtn').click()
            expect(banner).to_be_hidden()
            browser.close()
        self.assertTrue(WhiteboardDocument.objects.get(pk=document_id).class_visible)
        self.assertEqual(self.errors, [])

    # ---------- Travail à rendre ----------
    def test_assignment_copy_submission_and_correction(self):
        self.document.accepts_submissions = True
        self.document.title = 'Devoir limites'
        self.document.save()
        with sync_playwright() as pw:
            browser = self.launch(pw)
            _, student = self.context(browser, self.student)
            self.open(student, self.document.pk)
            expect(student.locator('#mbWorkBanner')).to_contain_text('Travail à rendre')
            expect(student.locator('#mbWorkBtn')).to_have_text('Faire ce travail')
            student.click('#mbWorkBtn')
            student.wait_for_url(lambda url: f'/tableau-maths/{self.document.pk}/' not in url)
            student.wait_for_function('window.MB && MB.Work && MB.board.documentInfo && MB.board.documentInfo.submission_status')
            copy_id = student.evaluate('MB.board.documentInfo.id')
            expect(student.locator('#mbWorkBanner')).to_contain_text('Votre copie de « Devoir limites »')
            self.assertTrue(student.locator('#mbShareBtn').is_hidden())
            student.click('[data-tool="rect"]')
            self.drag(student, 120, 120, 260, 200)
            self.wait_saved(student)
            student.click('#mbWorkBtn')
            student.click('#mbWorkSubmit')
            expect(student.locator('#mbWorkBanner')).to_contain_text('Travail rendu le')
            expect(student.locator('[data-tool="rect"]')).to_be_hidden()   # lecture seule

            _, teacher = self.context(browser, self.teacher)
            teacher.goto(self.live_server_url + reverse('mathboard:list'))
            expect(teacher.locator('#mbToGradeTitle')).to_contain_text('Travaux à corriger')
            # (Le même lien figure aussi dans la notification « Travail rendu ».)
            teacher.locator('section[aria-labelledby="mbToGradeTitle"]').locator(
                f'a[href="{reverse("mathboard:editor", args=[copy_id])}"]').click()
            teacher.wait_for_function('window.MB && MB.Work && MB.board.documentInfo')
            expect(teacher.locator('#mbWorkBanner')).to_contain_text('Copie de Salma Élève')
            teacher.click('[data-tool="ellipse"]')
            self.drag(teacher, 300, 120, 380, 180)
            self.wait_saved(teacher)
            teacher.click('#mbWorkBtn')
            teacher.fill('#mbWorkGrade', '15/20')
            teacher.fill('#mbWorkComment', 'Bonne idée, rédaction à soigner.')
            teacher.click('#mbWorkReturn')
            expect(teacher.locator('#mbWorkBanner')).to_contain_text('corrigée (15/20)')

            # L'élève (toujours sur sa copie, sans WebSocket) voit la correction arriver.
            expect(student.locator('#mbWorkBanner')).to_contain_text('note : 15/20', timeout=15000)
            student.wait_for_function('MB.board.canvas.getObjects().length === 2')
            student.click('#mbWorkBtn')
            expect(student.locator('#mbWorkFeedbackText')).to_have_text('Bonne idée, rédaction à soigner.')
            browser.close()
        self.assertEqual(self.errors, [])

    # ---------- Mode présentation ----------
    def test_presentation_is_followed_and_can_be_left(self):
        with sync_playwright() as pw:
            browser = self.launch(pw)
            _, student = self.context(browser, self.student, viewport={'width': 900, 'height': 700})
            self.open(student, self.document.pk)
            _, teacher = self.context(browser, self.teacher)
            self.open(teacher, self.document.pk)
            teacher.click('#mbAddPage')
            self.wait_saved(teacher)
            teacher.click('#mbPresentBtn')
            expect(teacher.locator('#mbBanner')).to_contain_text('Vous présentez')
            teacher.evaluate('MB.board.zoomBy(2); MB.board.canvas.relativePan(new fabric.Point(-150, 60)); MB.board.canvas.requestRenderAll()')
            teacher.wait_for_timeout(1000)   # le bandeau a pu réduire la hauteur du canevas : vue stabilisée
            teacher_view = teacher.evaluate('MB.Present.view()')
            expect(student.locator('#mbBanner')).to_contain_text('Karim Prof présente — vous suivez sa vue', timeout=10000)
            student.wait_for_function(
                '''(v) => { const p = MB.Present.current; if (!p || p.page !== v.page || MB.board.pageUid !== v.page) return false;
                   const mine = MB.Present.view(); return Math.abs(mine.cx - v.cx) < 2 && Math.abs(mine.cy - v.cy) < 2; }''',
                arg=teacher_view, timeout=10000)
            # La zone du professeur est entièrement visible chez l'élève (écran plus petit).
            student_view = student.evaluate('MB.Present.view()')
            self.assertGreaterEqual(student_view['w'] + 1, teacher_view['w'])
            student.click('#mbBannerActions button')                   # « Ne plus suivre »
            expect(student.locator('#mbBanner')).to_contain_text('Karim Prof présente.')
            teacher.click('#mbPresentBtn')
            expect(student.locator('#mbBanner')).to_be_hidden(timeout=10000)
            browser.close()
        self.assertEqual(self.errors, [])

    # ---------- Participation ----------
    def test_participation_shows_and_removes_a_students_work(self):
        self.document.students_can_edit = True
        self.document.save()
        with sync_playwright() as pw:
            browser = self.launch(pw)
            _, student = self.context(browser, self.student)
            self.open(student, self.document.pk)
            student.click('[data-tool="rect"]')
            self.drag(student, 100, 100, 200, 160)
            self.drag(student, 260, 100, 360, 160)
            self.wait_saved(student)
            _, teacher = self.context(browser, self.teacher)
            self.open(teacher, self.document.pk)
            teacher.click('[data-tool="ellipse"]')
            self.drag(teacher, 100, 300, 200, 360)
            self.wait_saved(teacher)
            teacher.click('#mbPeopleBtn')
            row = teacher.locator('#mbPeopleList li', has_text='Salma Élève')
            expect(row).to_contain_text('2 élément(s) sur 1 page(s)')
            row.get_by_role('button', name='Montrer').click()
            teacher.wait_for_function('MB.board.selected().length === 2')
            teacher.click('#mbPeopleBtn')
            teacher.locator('#mbPeopleList li', has_text='Salma Élève').get_by_role('button', name='Supprimer').click()
            teacher.wait_for_function('MB.board.canvas.getObjects().length === 1')
            self.wait_saved(teacher)
            objects = self.state(teacher, self.document.pk)['pages'][0]['objects']
            self.assertEqual([o['_by'] for o in objects.values()], [self.teacher.pk])
            student.wait_for_function('MB.board.canvas.getObjects().length === 1', timeout=10000)
            versions = teacher.evaluate("async (u) => (await fetch(u)).json()", reverse('mathboard:api_snapshots', args=[self.document.pk]))
            self.assertTrue(any('Avant suppression des éléments de Salma Élève' in v['label'] for v in versions))
            browser.close()
        self.assertEqual(self.errors, [])

    # ---------- Texte arabe ----------
    def test_arabic_text_is_written_right_to_left(self):
        with sync_playwright() as pw:
            browser = self.launch(pw)
            _, page = self.context(browser, self.teacher)
            self.open(page, self.document.pk)
            page.click('[data-tool="text"]')
            box = page.locator('#mbCanvasHost').bounding_box()
            page.mouse.click(box['x'] + 300, box['y'] + 200)
            page.keyboard.insert_text('الدالة f متزايدة')
            page.evaluate('MB.board.canvas.getActiveObject().exitEditing()')
            self.wait_saved(page)
            text = list(self.state(page, self.document.pk)['pages'][0]['objects'].values())[0]
            self.assertEqual((text['text'], text['direction'], text['textAlign']), ('الدالة f متزايدة', 'rtl', 'right'))
            page.reload()
            page.wait_for_function('MB.board && MB.board.canvas.getObjects().length === 1')
            self.assertEqual(page.evaluate('MB.board.canvas.getObjects()[0].direction'), 'rtl')
            browser.close()
        self.assertEqual(self.errors, [])

    # ---------- Stylet ----------
    def test_stylus_pressure_and_palm_rejection(self):
        with sync_playwright() as pw:
            browser = self.launch(pw)
            context, page = self.context(browser, self.teacher, has_touch=True)
            self.open(page, self.document.pk)
            cdp = context.new_cdp_session(page)
            box = page.locator('#mbCanvasHost').bounding_box()
            page.evaluate("MB.board.setTool('pen'); MB.board.setWidth(8)")

            def pen(kind, x, y, force):
                cdp.send('Input.dispatchMouseEvent', {'type': kind, 'x': box['x'] + x, 'y': box['y'] + y, 'button': 'left',
                                                      'buttons': 1 if kind != 'mouseReleased' else 0, 'clickCount': 1,
                                                      'pointerType': 'pen', 'force': force})
            pen('mousePressed', 100, 200, 0.1)
            for k in range(1, 21):
                pen('mouseMoved', 100 + k * 12, 200 + (k % 5) * 3, min(1.0, 0.1 + k * 0.045))
            pen('mouseReleased', 340, 212, 0.9)
            self.wait_saved(page)
            paths = [o for o in self.state(page, self.document.pk)['pages'][0]['objects'].values() if o['type'] == 'path']
            self.assertEqual(len(paths), 1)
            # Forme remplie (épaisseur variable) et non trait d'épaisseur constante.
            self.assertEqual(paths[0]['fill'], '#212529')
            self.assertIn(paths[0]['stroke'], (None, ''))
            expect(page.locator('#mbToast')).to_contain_text('Stylet détecté')

            # Après le stylet, un doigt (ou la paume) déplace la vue au lieu d'écrire.
            before = page.evaluate('MB.board.canvas.viewportTransform.slice()')
            touch = lambda kind, pts: cdp.send('Input.dispatchTouchEvent', {'type': kind, 'touchPoints': [
                {'x': box['x'] + x, 'y': box['y'] + y} for x, y in pts]})
            touch('touchStart', [(400, 400)])
            for k in range(1, 6):
                touch('touchMove', [(400 - 10 * k, 400 - 4 * k)])
            touch('touchEnd', [])
            page.wait_for_timeout(500)
            after = page.evaluate('MB.board.canvas.viewportTransform.slice()')
            self.assertAlmostEqual(after[4] - before[4], -50, delta=1)
            self.assertAlmostEqual(after[5] - before[5], -20, delta=1)
            self.assertEqual(page.evaluate('MB.board.canvas.getObjects().length'), 1)
            browser.close()
        self.assertEqual(self.errors, [])

    # ---------- Écriture → texte et formules ----------
    def test_handwriting_is_converted_to_text_and_formulas(self):
        import base64
        import io
        import json
        from PIL import Image
        sent = []
        reply = {'lines': [
            {'segments': [{'kind': 'text', 'content': 'Soit'}, {'kind': 'math', 'content': 'f(x)=x^2+1'}]},
            {'segments': [{'kind': 'text', 'content': 'الدالة'}, {'kind': 'math', 'content': 'f'},
                          {'kind': 'text', 'content': 'متزايدة'}]},
            {'segments': [{'kind': 'text', 'content': 'Conclusion'}]},
        ]}

        def recognize(route):
            sent.append(json.loads(route.request.post_data)['image'])
            route.fulfill(status=200, content_type='application/json', body=json.dumps(reply))

        with override_settings(MATHBOARD_HANDWRITING_ENABLED=True, ANTHROPIC_API_KEY='test'), sync_playwright() as pw:
            browser = self.launch(pw)
            _, page = self.context(browser, self.teacher)
            page.route('**/api/documents/*/ecriture/', recognize)   # service externe simulé
            self.open(page, self.document.pk)
            page.click('[data-tool="pen"]')
            self.drag(page, 100, 100, 260, 140)
            self.drag(page, 120, 180, 300, 220)
            page.wait_for_function('MB.board.canvas.getObjects().length === 2')
            page.click('[data-tool="select"]')
            page.evaluate('MB.board.selectAll()')
            convert = page.locator('#mbSelectionBar [data-act="convert"]')
            expect(convert).to_be_visible()
            convert.click()
            expect(page.locator('#mbInkSource')).to_have_value(
                'Soit \\(f(x)=x^2+1\\)\nالدالة \\(f\\) متزايدة\nConclusion')
            expect(page.locator('#mbInkPreview .mb-ink-line')).to_have_count(3)
            expect(page.locator('#mbInkPreview .mb-ink-line').nth(1)).to_have_attribute('dir', 'rtl')
            expect(page.locator('#mbInkPreview .mb-ink-math img').first).to_be_visible()
            # Le professeur corrige le résultat avant l'insertion.
            page.locator('#mbInkSource').fill('Soit \\(f(x)=x^2-1\\)\nالدالة \\(f\\) متزايدة\nConclusion')
            page.locator('#mbInkInsert').click()
            expect(page.locator('#mbInkDialog')).not_to_be_visible()
            page.wait_for_function('MB.board.canvas.getObjects().length === 3')
            self.wait_saved(page)
            objects = sorted(self.state(page, self.document.pk)['pages'][0]['objects'].values(), key=lambda o: o['top'])
            # Annuler rend l'écriture manuscrite d'un seul coup.
            page.keyboard.press('Control+z')
            page.wait_for_function("MB.board.canvas.getObjects().every(o => o.type.toLowerCase() === 'path')")
            browser.close()
        self.assertEqual([o['type'] for o in objects], ['math', 'math', 'i-text'])
        self.assertEqual(objects[0]['latex'], '\\text{ Soit } f(x)=x^2-1')
        self.assertEqual(objects[1]['latex'], '\\text{ متزايدة } f \\text{ الدالة }')    # arabe : ordre de droite à gauche
        self.assertEqual(objects[2]['text'], 'Conclusion')
        # Image envoyée : uniquement les traits, en noir sur blanc.
        self.assertEqual(len(sent), 1)
        image = Image.open(io.BytesIO(base64.b64decode(sent[0].split(',', 1)[1]))).convert('L')
        self.assertLess(image.getextrema()[0], 80)
        self.assertEqual(image.getpixel((0, 0)), 255)
        self.assertEqual(self.errors, [])

    # ---------- Images en fichiers ----------
    def test_imported_image_is_uploaded_as_a_file(self):
        media = tempfile.mkdtemp()
        try:
            with override_settings(MEDIA_ROOT=media), sync_playwright() as pw:
                browser = self.launch(pw)
                context, page = self.context(browser, self.teacher)
                self.open(page, self.document.pk)
                image = os.path.join(media, 'source.png')
                from PIL import Image
                Image.new('RGB', (300, 200), (30, 120, 200)).save(image)
                page.set_input_files('#mbImageFile', image)
                page.wait_for_function('MB.board.canvas.getObjects().length === 1')
                self.wait_saved(page)
                obj = list(self.state(page, self.document.pk)['pages'][0]['objects'].values())[0]
                self.assertRegex(obj['src'], rf'^/tableau-maths/{self.document.pk}/images/[0-9a-f]{{32}}\.png$')
                self.assertTrue(os.path.exists(os.path.join(media, 'mathboard', str(self.document.pk), obj['src'].rsplit('/', 1)[1])))
                # Servie par Django (aucune correspondance /media/ en production) : rechargée et affichée.
                page.reload()
                page.wait_for_function('MB.board && MB.board.canvas.getObjects().length === 1')
                page.wait_for_function('MB.board.canvas.getObjects()[0].getElement().naturalWidth === 300')
                browser.close()
        finally:
            shutil.rmtree(media, ignore_errors=True)
        self.assertEqual(self.errors, [])

    # ---------- Hors connexion ----------
    def test_board_opens_offline_from_the_last_copy(self):
        with sync_playwright() as pw:
            browser = self.launch(pw)
            context, page = self.context(browser, self.teacher, service_workers='allow')
            self.open(page, self.document.pk)
            page.click('[data-tool="rect"]')
            self.drag(page, 100, 100, 220, 180)
            self.wait_saved(page)
            page.evaluate("navigator.serviceWorker.ready.then(() => true)")
            page.reload()                       # page contrôlée par le service worker : copie gardée
            page.wait_for_function('window.MB && MB.board && MB.board.canvas.getObjects().length === 1')
            page.wait_for_timeout(2000)         # copie locale de l'état (1,5 s)
            context.set_offline(True)
            page.reload()
            page.wait_for_function('window.MB && MB.board && MB.board.canvas.getObjects().length === 1', timeout=15000)
            expect(page.locator('#mbToast')).to_contain_text('Hors ligne : dernière version enregistrée sur cet appareil')
            page.click('[data-tool="ellipse"]')
            self.drag(page, 300, 100, 380, 160)
            expect(page.locator('#mbStatus')).to_contain_text('Hors ligne — 1 modification en attente')
            context.set_offline(False)
            page.evaluate("window.dispatchEvent(new Event('online'))")
            self.wait_saved(page)
            self.assertEqual(len(self.state(page, self.document.pk)['pages'][0]['objects']), 2)
            # Déconnexion : la page gardée est effacée.
            page.goto(self.live_server_url + reverse('accounts:logout'))
            page.wait_for_timeout(500)
            self.assertFalse(page.evaluate("caches.has('edubac-boards')"))
            browser.close()
        self.assertEqual([e for e in self.errors if 'ERR_INTERNET_DISCONNECTED' not in e and 'Failed to fetch' not in e], [])

    # ---------- Ancien tableau ----------
    def test_old_board_is_converted_from_its_list(self):
        board = WhiteboardBoard.objects.create(title='Ancien cours', created_by=self.teacher, content={
            'version': 1, 'background': 'grid', 'objects': [
                {'id': 'r', 'type': 'rect', 'x': 100, 'y': 100, 'w': 60, 'h': 40, 'color': '#1971c2', 'size': 2},
                {'id': 'm', 'type': 'math', 'latex': '\\sqrt{2}', 'x': 300, 'y': 80},
            ]})
        with sync_playwright() as pw:
            browser = self.launch(pw)
            _, page = self.context(browser, self.teacher)
            page.goto(self.live_server_url + reverse('whiteboard:list'))
            page.get_by_role('button', name='Convertir vers le tableau mathématique').click()
            page.wait_for_url(lambda url: '/tableau-maths/' in url)
            page.wait_for_function('window.MB && MB.board && MB.board.canvas.getObjects().length === 2', timeout=15000)
            expect(page.locator('.alert, .toast, [role="alert"]').first).to_contain_text('Tableau converti : 2 élément(s)')
            rect = page.evaluate("MB.board.canvas.getObjects().find(o => o.type === 'rect').getBoundingRect()")
            self.assertAlmostEqual(rect['left'], 99, delta=1.5)
            self.assertAlmostEqual(rect['width'], 62, delta=1.5)
            browser.close()
        self.assertTrue(WhiteboardDocument.objects.filter(legacy_board=board).exists())
        self.assertEqual(self.errors, [])
