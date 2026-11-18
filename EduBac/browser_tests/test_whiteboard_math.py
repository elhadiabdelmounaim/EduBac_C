"""Repère interactif dans le vrai navigateur : création, curseur synchronisé,
tableau de variations généré, arbre, exercice « placer un point » côté élève.
Captures facultatives : CHAT_SCREENSHOT_DIR=/dossier.
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

OBJECTS = 'window.EduBacBoard.getObjects()'
TO_PAGE = """([X, Y]) => { const c = document.getElementById('wbCanvas'), r = c.getBoundingClientRect();
  return {x: r.left + X * r.width / c.width, y: r.top + Y * r.height / c.height}; }"""


class WhiteboardMathBrowserTests(StaticLiveServerTestCase):
    server_thread_class = SingleThreadLiveServer

    def setUp(self):
        self.teacher = User.objects.create_user(username='math-prof', email='mp@example.test', password=PASSWORD,
                                                role='teacher', first_name='Nadia', last_name='Benali')
        self.omar = User.objects.create_user(username='math-omar', email='mo@example.test', password=PASSWORD,
                                             role='student', first_name='Omar', last_name='Alaoui')
        classroom = Classroom.objects.create(name='2BAC SM', niveau='tronc_commun', teacher=self.teacher)
        classroom.add_member(self.omar)
        self.board = WhiteboardBoard.objects.create(title='Fonctions', created_by=self.teacher, classroom=classroom,
                                                    content={'version': 1, 'objects': []}, students_can_edit=True)

    def shot(self, page, name):
        folder = os.environ.get('CHAT_SCREENSHOT_DIR')
        if folder:
            page.screenshot(path=os.path.join(folder, f'math-{name}.png'))

    def open(self, browser, user):
        context = browser.new_context(viewport={'width': 1440, 'height': 950})
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

    def layout(self, page, index=0):
        return page.evaluate(f"""() => {{ const o = window.EduBacBoard._collab.objects().filter(x => x.type === 'plot')[{index}];
          return {{sliders: o._layout.sliders.map(s => ({{x: s.x, y: s.y, w: s.w, h: s.h, name: s.name}})), x: o.x, y: o.y, w: o.w, h: o.h}}; }}""")

    def test_plot_slider_table_tree_and_exercise(self):
        self.errors = []
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=os.environ.get('CHROMIUM_EXECUTABLE') or shutil.which('chromium'),
                                         headless=True, args=['--no-sandbox'])
            try:
                _, teacher = self.open(browser, self.teacher)
                # 1. Repère « second degré » depuis un modèle, avec aperçu.
                teacher.locator('#wbGraphBtn').click()
                expect(teacher.locator('#wbPlotEditor')).to_be_visible()
                teacher.locator('#wbPlotPreset').select_option('second')
                expect(teacher.locator('#wbPlotItems li')).to_have_count(6)
                expect(teacher.locator('#wbPlotItems .is-error')).to_have_count(0)
                # Commande invalide : message clair, rien n'est ajouté.
                teacher.locator('#wbPlotCmd').fill('g(x)=ax+1')
                teacher.locator('#wbPlotAdd').click()
                expect(teacher.locator('#wbPlotCmdError')).to_contain_text('a*x')
                teacher.locator('#wbPlotCmd').fill('T=Tangente(f;2)')
                teacher.locator('#wbPlotCmd').press('Enter')
                expect(teacher.locator('#wbPlotItems li')).to_have_count(7)
                self.shot(teacher, 'editor')
                teacher.locator('#wbPlotSave').click()
                teacher.wait_for_function(f"{OBJECTS}.filter(o => o.type === 'plot').length === 1")

                # 2. Curseur « a » déplacé au maximum : la valeur est enregistrée et synchronisée.
                slider = self.layout(teacher)['sliders'][0]
                start = teacher.evaluate(TO_PAGE, [slider['x'], slider['y'] + slider['h'] / 2])
                end = teacher.evaluate(TO_PAGE, [slider['x'] + slider['w'] + 20, slider['y'] + slider['h'] / 2])
                teacher.mouse.move(start['x'], start['y']); teacher.mouse.down()
                for step in range(1, 8):
                    teacher.mouse.move(start['x'] + (end['x'] - start['x']) * step / 7, end['y'])
                teacher.mouse.up()
                teacher.wait_for_function(f"{OBJECTS}[0].items[0].val === 3")
                self.shot(teacher, 'slider')

                # 3. Tableau de variations généré depuis le repère, arbre de probabilités.
                plot = self.layout(teacher)
                header = teacher.evaluate(TO_PAGE, [plot['x'] + 60, plot['y'] + 12])
                teacher.mouse.dblclick(header['x'], header['y'])
                expect(teacher.locator('#wbPlotEditor')).to_be_visible()
                expect(teacher.locator('#wbPlotTableFn')).to_have_value('f')
                teacher.locator('#wbPlotTableGen').click()
                teacher.wait_for_function(f"{OBJECTS}.some(o => o.type === 'vartable' && o.text.includes('↘'))")
                teacher.locator('#wbPlotCancel').click()
                teacher.locator('#wbTreeBtn').click()
                expect(teacher.locator('#wbTextObjError')).to_have_text('')
                teacher.locator('#wbTextObjSave').click()
                teacher.wait_for_function(f"{OBJECTS}.some(o => o.type === 'probtree')")

                # 4. Exercice : un second repère « placer des points ».
                teacher.locator('#wbGraphBtn').click()
                teacher.locator('#wbPlotPreset').select_option('exercice')
                teacher.locator('#wbPlotSave').click()
                teacher.wait_for_function(f"{OBJECTS}.filter(o => o.type === 'plot').length === 2")
                # Le nouveau repère ne recouvre pas le premier.
                first, second = teacher.evaluate(f"{OBJECTS}.filter(o => o.type === 'plot').map(o => [o.x, o.y, o.w, o.h])")
                self.assertTrue(second[1] >= first[1] + first[3] or second[0] >= first[0] + first[2], (first, second))
                self.shot(teacher, 'board')

                _, omar = self.open(browser, self.omar)
                omar.wait_for_function(f"{OBJECTS}.filter(o => o.type === 'plot').length === 2")
                # L'élève voit le même curseur que le professeur.
                self.assertEqual(omar.evaluate(f"{OBJECTS}[0].items[0].val"), 3)
                omar.wait_for_function("window.EduBacBoard._collab.objects().filter(o => o.type === 'plot')[1]._layout")
                omar.locator('.wb-tool[data-tool="select"]').click()
                # Il place A(2 ; 3) dans le second repère.
                target = omar.evaluate("""() => { const o = window.EduBacBoard._collab.objects().filter(x => x.type === 'plot')[1];
                  const p = window.EduBacPlot.fromMath(o, {x: 2, y: 3}); return [p.x, p.y]; }""")
                click = omar.evaluate(TO_PAGE, target)
                omar.mouse.click(click['x'], click['y'])
                omar.wait_for_function(f"{OBJECTS}.some(o => o.type === 'plotanswer' && o.target === 'A')")
                answer = omar.evaluate(f"{OBJECTS}.find(o => o.type === 'plotanswer')")
                self.assertLess(abs(answer['mx'] - 2) + abs(answer['my'] - 3), 0.3)
                # Elle est dessinée en vert (juste) sur l'écran de l'élève, tout de suite.
                rgb = omar.evaluate("""([X, Y]) => { const d = document.getElementById('wbCanvas').getContext('2d')
                  .getImageData(Math.round(X), Math.round(Y), 1, 1).data; return [d[0], d[1], d[2]]; }""", target)
                self.assertEqual(rgb, [0x2b, 0x8a, 0x3e])
                self.assertFalse(omar.locator('#wbSelectionBar').is_visible())
                self.shot(omar, 'student-answer')
                # Le professeur reçoit la réponse.
                teacher.wait_for_function(f"{OBJECTS}.some(o => o.type === 'plotanswer')", timeout=15000)
                self.assertEqual(self.errors, [])
            finally:
                browser.close()
