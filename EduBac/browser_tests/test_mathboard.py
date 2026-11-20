"""Tableau mathématique (phases 2 à 9) dans Chrome : dessin, sélection, calques,
annulation, copier-coller, pages, formules (MathLive + MathJax + SymPy),
figures (JSXGraph), collaboration à deux, coupure réseau, versions, export."""
import json
import os
import shutil

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from accounts.models import User
from classrooms.models import Classroom
from mathboard.models import WhiteboardDocument, WhiteboardPage

from .test_chat_moderation import PASSWORD, SingleThreadLiveServer


class MathboardBrowserTests(StaticLiveServerTestCase):
    server_thread_class = SingleThreadLiveServer

    def setUp(self):
        self.teacher = User.objects.create_user(username='prof-maths', email='pm@example.test', password=PASSWORD,
                                                role='teacher', first_name='Karim', last_name='Prof')
        self.student = User.objects.create_user(username='eleve-maths', email='em@example.test', password=PASSWORD,
                                                role='student', first_name='Salma', last_name='Élève')
        self.classroom = Classroom.objects.create(name='1bac1', niveau='1bac_sm', teacher=self.teacher)
        self.classroom.add_member(self.student)
        self.document = WhiteboardDocument.objects.create(title='Séance', owner=self.teacher, classroom=self.classroom,
                                                          level='1bac_sm', chapter='Fonctions')
        WhiteboardPage.objects.create(document=self.document, uid='page-1', position=0, background='grid')

    def launch(self, pw):
        return pw.chromium.launch(executable_path=os.environ.get('CHROMIUM_EXECUTABLE') or shutil.which('chromium'),
                                  headless=True, args=['--no-sandbox'])

    def open(self, browser, user, errors):
        self.errors = errors
        context = browser.new_context(viewport={'width': 1366, 'height': 860})
        page = context.new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
        page.goto(self.live_server_url + reverse('accounts:login'))
        page.locator('input[name="username"]').fill(user.username)
        page.locator('input[name="password"]').fill(PASSWORD)
        page.locator('form button[type="submit"]').first.click()
        page.wait_for_url(lambda url: '/connexion/' not in url)
        page.goto(self.live_server_url + reverse('mathboard:editor', args=[self.document.pk]))
        page.wait_for_function('window.MB && MB.board && MB.board.pages.length > 0')
        self.page = page
        return page

    def state(self):
        """État lu par l'API depuis le navigateur (pas d'accès ORM dans le contexte Playwright)."""
        return self.page.evaluate("""async (url) => (await fetch(url, {credentials: 'same-origin'})).json()""",
                                  reverse('mathboard:api_state', args=[self.document.pk]))

    def objects(self, uid='page-1'):
        return next(p for p in self.state()['pages'] if p['uid'] == uid)['objects']

    def wait_saved(self, page):
        try:
            page.wait_for_function("document.getElementById('mbStatus').dataset.state === 'saved'", timeout=15000)
        except Exception:
            raise AssertionError('Statut : %s ; erreurs : %s' % (
                page.locator('#mbStatus').text_content(), getattr(self, 'errors', None)))

    def drag(self, page, x1, y1, x2, y2):
        box = page.locator('#mbCanvasHost').bounding_box()
        page.mouse.move(box['x'] + x1, box['y'] + y1)
        page.mouse.down()
        page.mouse.move(box['x'] + (x1 + x2) / 2, box['y'] + (y1 + y2) / 2, steps=4)
        page.mouse.move(box['x'] + x2, box['y'] + y2, steps=4)
        page.mouse.up()

    def test_smoke_draw_rectangle(self):
        errors = []
        with sync_playwright() as pw:
            browser = self.launch(pw)
            page = self.open(browser, self.teacher, errors)
            page.click('[data-tool="rect"]')
            self.drag(page, 100, 100, 260, 200)
            self.wait_saved(page)
            rects = [o for o in self.objects().values() if o['type'] == 'rect']
            self.assertEqual(len(rects), 1, self.objects())
            browser.close()
        self.assertEqual(errors, [])

    # ---------- helpers ----------
    def screen_point(self, page, oid):
        """Centre écran d'un objet du canevas."""
        point = page.evaluate("""(id) => { const o = MB.board.byId[id]; const c = o.getCenterPoint();
            const v = MB.board.canvas.viewportTransform; return {x: c.x * v[0] + v[4], y: c.y * v[3] + v[5]}; }""", oid)
        box = page.locator('#mbCanvasHost').bounding_box()
        return box['x'] + point['x'], box['y'] + point['y']

    def by_type(self, kind):
        return [o for o in self.objects().values() if o['type'] == kind]

    # ---------- Phase 2 : canevas Fabric.js ----------
    def test_canvas_tools_selection_layers_history_clipboard_pages(self):
        errors = []
        with sync_playwright() as pw:
            browser = self.launch(pw)
            page = self.open(browser, self.teacher, errors)
            # Crayon
            page.click('[data-tool="pen"]')
            self.drag(page, 80, 300, 220, 360)
            # Rectangle et ellipse
            page.click('[data-tool="rect"]')
            self.drag(page, 100, 80, 240, 180)
            page.click('[data-tool="ellipse"]')
            self.drag(page, 300, 80, 420, 170)
            # Flèche
            page.click('[data-tool="arrow"]')
            self.drag(page, 460, 100, 600, 200)
            # Texte
            page.click('[data-tool="text"]')
            box = page.locator('#mbCanvasHost').bounding_box()
            page.mouse.click(box['x'] + 500, box['y'] + 320)
            page.keyboard.type('Soit f(x) = x²')
            page.keyboard.press('Escape')
            self.wait_saved(page)
            kinds = sorted(o['type'] for o in self.objects().values())
            self.assertEqual(kinds, ['ellipse', 'i-text', 'path', 'path', 'rect'], kinds)
            self.assertEqual(self.by_type('i-text')[0]['text'], 'Soit f(x) = x²')

            # Calques : le rectangle passe à l'arrière-plan, puis annuler / rétablir.
            rect_id = self.by_type('rect')[0]['id']
            page.click('[data-tool="select"]')
            page.mouse.click(*self.screen_point(page, rect_id))
            expect(page.locator('#mbSelectionBar')).to_be_visible()
            page.click('#mbSelectionBar [data-act="back"]')
            self.wait_saved(page)
            zs = {o['id']: o['z'] for o in self.objects().values()}
            self.assertEqual(min(zs, key=zs.get), rect_id)
            page.keyboard.press('Control+z')
            self.wait_saved(page)
            zs = {o['id']: o['z'] for o in self.objects().values()}
            self.assertNotEqual(min(zs, key=zs.get), rect_id)
            page.keyboard.press('Control+y')
            self.wait_saved(page)
            zs = {o['id']: o['z'] for o in self.objects().values()}
            self.assertEqual(min(zs, key=zs.get), rect_id)

            # Sélection multiple + déplacement : chaque objet garde des coordonnées absolues.
            before = {o['id']: (o['left'], o['top']) for o in self.objects().values()}
            page.keyboard.press('Control+a')
            x, y = self.screen_point(page, rect_id)
            page.mouse.move(x, y); page.mouse.down(); page.mouse.move(x + 60, y + 40, steps=5); page.mouse.up()
            self.wait_saved(page)
            after = {o['id']: (o['left'], o['top']) for o in self.objects().values()}
            for oid, (left, top) in before.items():
                self.assertAlmostEqual(after[oid][0] - left, 60, delta=2)
                self.assertAlmostEqual(after[oid][1] - top, 40, delta=2)

            # Copier / coller puis supprimer.
            page.keyboard.press('Escape')
            page.mouse.click(*self.screen_point(page, rect_id))
            page.keyboard.press('Control+c')
            page.keyboard.press('Control+v')
            self.wait_saved(page)
            self.assertEqual(len(self.by_type('rect')), 2)
            page.keyboard.press('Delete')
            self.wait_saved(page)
            self.assertEqual(len(self.by_type('rect')), 1)
            page.keyboard.press('Control+z')
            self.wait_saved(page)
            self.assertEqual(len(self.by_type('rect')), 2)

            # Gomme
            ellipse_id = self.by_type('ellipse')[0]['id']
            page.click('[data-tool="eraser"]')
            x, y = self.screen_point(page, ellipse_id)
            page.mouse.move(x - 50, y); page.mouse.down(); page.mouse.move(x + 50, y, steps=8); page.mouse.up()
            self.wait_saved(page)
            self.assertEqual(self.by_type('ellipse'), [])

            # Pages, fond et zoom
            page.click('#mbAddPage')
            self.wait_saved(page)
            self.assertEqual(len(self.state()['pages']), 2)
            page.select_option('#mbBackground', 'axes')
            self.wait_saved(page)
            self.assertEqual(self.state()['pages'][1]['background'], 'axes')
            page.click('#mbPages .mb-page >> nth=0')
            page.click('#mbZoomIn')
            expect(page.locator('#mbZoomValue')).to_have_text('120 %')
            browser.close()
        self.assertEqual(errors, [])

    # ---------- Phase 3 : formules et calcul exact ----------
    def test_math_formula_and_sympy_calculation(self):
        errors = []
        with sync_playwright() as pw:
            browser = self.launch(pw)
            page = self.open(browser, self.teacher, errors)
            page.click('#mbMathBtn')
            page.wait_for_function("customElements.get('math-field') !== undefined")
            page.evaluate("document.getElementById('mbMathField').value = 'x^2-5x+6'")
            page.select_option('#mbCalcAction', 'factor')
            page.click('#mbCalcRun')
            expect(page.locator('#mbCalcResult img')).to_be_visible(timeout=15000)
            page.click('#mbCalcInsert')
            page.click('#mbMathSave')
            self.wait_saved(page)
            latex = sorted(o['latex'] for o in self.by_type('math'))
            self.assertEqual(latex, ['\\left(x - 3\\right) \\left(x - 2\\right)', 'x^2-5x+6'])
            # Modifier la formule (double-clic) : l'objet reste le même, son LaTeX change.
            oid = [o['id'] for o in self.by_type('math') if o['latex'] == 'x^2-5x+6'][0]
            page.mouse.dblclick(*self.screen_point(page, oid))
            expect(page.locator('#mbMathDialog')).to_be_visible()
            page.evaluate("document.getElementById('mbMathField').value = '\\\\frac{1}{x}'")
            page.click('#mbMathSave')
            self.wait_saved(page)
            self.assertEqual(self.objects()[oid]['latex'], '\\frac{1}{x}')
            # Erreur de calcul affichée en français, rien n'est inséré.
            page.click('#mbMathBtn')
            page.evaluate("document.getElementById('mbMathField').value = '\\\\frac{1}{x}'")
            page.select_option('#mbCalcAction', 'determinant')
            page.click('#mbCalcRun')
            expect(page.locator('#mbCalcResult .mb-error')).to_contain_text('matrice')
            browser.close()
        self.assertEqual(errors, [])

    # ---------- Phase 4 : figures JSXGraph + SymPy ----------
    def test_geometry_figure_asymptotes_and_variation_table(self):
        errors = []
        with sync_playwright() as pw:
            browser = self.launch(pw)
            page = self.open(browser, self.teacher, errors)
            page.click('#mbGeoBtn')
            page.fill('#mbGeoScript', 'f(x) = (x^2+1)/(x-1)\nA = (-2, 1)\nB = (2, 3)\nd = Droite(A, B)\nI = Intersection(d, f)')
            page.dispatch_event('#mbGeoScript', 'input')
            page.wait_for_timeout(600)
            self.assertEqual(page.locator('#mbGeoErrors li').count(), 0)
            page.click('#mbGeoAsym')
            expect(page.locator('#mbGeoScript')).to_have_value(__import__('re').compile(r'Verticale\(1\)'), timeout=15000)
            self.assertIn('as1(x) = 1*x + 1', page.input_value('#mbGeoScript'))
            page.click('#mbGeoVar')
            expect(page.locator('#mbGeoError')).to_contain_text('ajouté', timeout=15000)
            page.fill('#mbGeoScript', page.input_value('#mbGeoScript') + '\nmauvais = Truc(A)')
            page.dispatch_event('#mbGeoScript', 'input')
            expect(page.locator('#mbGeoErrors li')).to_contain_text('Commande inconnue')
            page.fill('#mbGeoScript', page.input_value('#mbGeoScript').replace('\nmauvais = Truc(A)', ''))
            page.click('#mbGeoSave')
            self.wait_saved(page)
            geometry = self.by_type('geometry')
            self.assertEqual(len(geometry), 1)
            self.assertIn('Verticale(1)', geometry[0]['script'])
            table = [o for o in self.by_type('math') if 'array' in o['latex']]
            self.assertEqual(len(table), 1)
            self.assertIn('\\Vert', table[0]['latex'])
            browser.close()
        self.assertEqual(errors, [])

    # ---------- Phase 5 : collaboration à deux ----------
    def test_teacher_and_student_collaborate_with_permissions(self):
        errors = []
        with sync_playwright() as pw:
            browser = self.launch(pw)
            teacher = self.open(browser, self.teacher, errors)
            teacher.click('[data-tool="rect"]')
            self.drag(teacher, 100, 100, 220, 180)
            self.wait_saved(teacher)
            student = self.open(browser, self.student, errors)
            # Lecture seule : outils d'écriture cachés, mention affichée, figure du professeur visible.
            expect(student.locator('#mbRole')).to_have_text('Lecture seule')
            expect(student.locator('[data-tool="pen"]')).to_be_hidden()
            expect(student.locator('#mbShareBtn')).to_be_hidden()
            student.wait_for_function("Object.keys(MB.board.byId).length === 1")
            # Nouvelle figure du professeur : l'élève la reçoit sans recharger.
            teacher.click('[data-tool="ellipse"]')
            self.drag(teacher, 300, 100, 400, 180)
            self.wait_saved(teacher)
            student.wait_for_function("Object.keys(MB.board.byId).length === 2", timeout=10000)
            # Présence : chacun voit l'autre.
            teacher.wait_for_function("document.querySelectorAll('#mbPresence .mb-avatar').length === 2", timeout=12000)
            # Le professeur autorise l'écriture des élèves (fenêtre Partager).
            teacher.click('#mbShareBtn')
            teacher.check('#mbShareEdit')
            teacher.click('#mbShareSave')
            expect(teacher.locator('#mbToast')).to_contain_text('Réglages enregistrés')
            teacher.click('#mbShareDialog button[value="close"]')
            student.reload()
            student.wait_for_function('window.MB && MB.board && MB.board.access === "edit"')
            expect(student.locator('[data-tool="pen"]')).to_be_visible()
            student.click('[data-tool="pen"]')
            self.drag(student, 120, 300, 260, 340)
            self.wait_saved(student)
            teacher.wait_for_function("Object.keys(MB.board.byId).length === 3", timeout=10000)
            # L'élève ne peut pas sélectionner (donc ni déplacer ni supprimer) la figure du professeur.
            rect_id = [o['id'] for o in self.objects().values() if o['type'] == 'rect'][0]
            selectable = student.evaluate("(id) => MB.board.byId[id].selectable", rect_id)
            self.assertFalse(selectable)
            student.click('[data-tool="select"]')
            student.mouse.click(*self.screen_point(student, rect_id))
            student.keyboard.press('Delete')
            student.wait_for_timeout(800)
            self.assertEqual(len([o for o in self.objects().values() if o['type'] == 'rect']), 1)
            browser.close()
        self.assertEqual(errors, [])

    # ---------- Phase 6 : coupure réseau, file d'attente, versions ----------
    def test_offline_queue_survives_reload_and_versions_restore(self):
        errors = []
        with sync_playwright() as pw:
            browser = self.launch(pw)
            page = self.open(browser, self.teacher, errors)
            ops_url = '**' + reverse('mathboard:api_operations', args=[self.document.pk])
            page.route(ops_url, lambda route: route.abort() if route.request.method == 'POST' else route.continue_())
            page.click('[data-tool="rect"]')
            self.drag(page, 100, 100, 220, 180)
            expect(page.locator('#mbStatus')).to_contain_text('nouvel essai', timeout=10000)
            pending = page.evaluate("JSON.parse(localStorage.getItem('mathboard:pending:%d') || '[]').length" % self.document.pk)
            self.assertEqual(pending, 1)
            # Rechargement pendant la coupure : la modification est toujours affichée.
            page.reload()
            page.wait_for_function('window.MB && MB.board && MB.board.pages.length > 0')
            page.wait_for_function("Object.keys(MB.board.byId).length === 1")
            self.assertEqual(self.objects(), {})
            # Retour du réseau : envoi automatique, rien n'est perdu.
            page.unroute(ops_url)
            self.wait_saved(page)
            self.assertEqual([o['type'] for o in self.objects().values()], ['rect'])
            # Hors ligne déclaré par le navigateur.
            page.context.set_offline(True)
            page.click('[data-tool="ellipse"]')
            self.drag(page, 300, 100, 400, 180)
            expect(page.locator('#mbStatus')).to_contain_text('Hors ligne — 1 modification en attente')
            page.context.set_offline(False)
            self.wait_saved(page)
            self.assertEqual(sorted(o['type'] for o in self.objects().values()), ['ellipse', 'rect'])
            # Versions : créer, modifier, restaurer.
            page.click('#mbVersionsBtn')
            page.fill('#mbVersionLabel', 'Deux figures')
            page.click('#mbVersionCreate')
            expect(page.locator('#mbVersionsList')).to_contain_text('Deux figures')
            page.click('#mbVersionsDialog button[value="close"]')
            page.keyboard.press('Control+a')
            page.keyboard.press('Delete')
            self.wait_saved(page)
            self.assertEqual(self.objects(), {})
            page.click('#mbVersionsBtn')
            page.once('dialog', lambda d: d.accept())
            page.locator('#mbVersionsList li', has_text='Deux figures').get_by_role('button', name='Restaurer').click()
            expect(page.locator('#mbToast')).to_contain_text('Version restaurée')
            page.wait_for_function("Object.keys(MB.board.byId).length === 2")
            self.assertEqual(sorted(o['type'] for o in self.objects().values()), ['ellipse', 'rect'])
            browser.close()
        self.assertEqual([e for e in errors if 'net::ERR' not in e and 'Failed to fetch' not in e], [])

    # ---------- Phase 8 : export / import ; Phase 7 : assistant non configuré ----------
    def test_export_import_and_assistant_message(self):
        errors = []
        with sync_playwright() as pw:
            browser = self.launch(pw)
            page = self.open(browser, self.teacher, errors)
            page.click('[data-tool="rect"]')
            self.drag(page, 100, 100, 220, 180)
            self.wait_saved(page)
            page.click('#mbExportBtn')
            with page.expect_download() as png:
                page.click('[data-export="png"]')
            self.assertTrue(png.value.suggested_filename.endswith('.png'))
            page.click('#mbExportBtn')
            with page.expect_download() as svg:
                page.click('[data-export="svg"]')
            self.assertIn('<svg', open(svg.value.path(), encoding='utf-8').read())
            exported = page.evaluate("async (u) => (await fetch(u)).json()",
                                     reverse('mathboard:api_export', args=[self.document.pk]))
            self.assertEqual(exported['format'], 'edubac-mathboard')
            path = os.path.join(os.environ.get('TMPDIR', '/tmp'), 'mb-export-test.json')
            with open(path, 'w', encoding='utf-8') as handle:
                json.dump(exported, handle)
            # Assistant IA : message clair quand le service n'est pas configuré.
            page.click('#mbAiBtn')
            page.fill('#mbAiQuestion', 'Comment factoriser ?')
            page.click('[data-ai="hint"]')
            expect(page.locator('#mbAiResult')).to_contain_text('pas encore configuré')
            # Import depuis la liste : nouveau document identique.
            page.goto(self.live_server_url + reverse('mathboard:list'))
            page.set_input_files('#mbImportFile', path)
            page.wait_for_url(lambda url: '/tableau-maths/' in url and not url.endswith('/tableau-maths/'))
            page.wait_for_function('window.MB && MB.board && Object.keys(MB.board.byId).length === 1')
            browser.close()
        os.remove(path)
        self.assertEqual([e for e in errors if '503' not in e], [])
