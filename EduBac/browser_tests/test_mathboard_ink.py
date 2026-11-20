"""Tableau mathématique dans Chrome : écriture manuscrite sans IA générative —
tracés bruts, lasso, formes, gomme intelligente, conversion texte / formule
(moteur de reconnaissance simulé)."""
import json
import math

from django.test import override_settings
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from .test_mathboard_class import MathboardBrowserBase


def circle(cx, cy, r, n=40, turns=1.0):
    return [(cx + r * math.cos(2 * math.pi * turns * i / n), cy + r * math.sin(2 * math.pi * turns * i / n)) for i in range(n + 1)]


def polyline(*corners, steps=12):
    pts = []
    for (x1, y1), (x2, y2) in zip(corners, corners[1:]):
        pts += [(x1 + (x2 - x1) * k / steps, y1 + (y2 - y1) * k / steps) for k in range(steps)]
    return pts + [corners[-1]]


class MathboardInkBrowserTests(MathboardBrowserBase):

    # ---------- outils ----------
    def stroke(self, page, points):
        box = page.locator('#mbCanvasHost').bounding_box()
        page.mouse.move(box['x'] + points[0][0], box['y'] + points[0][1])
        page.mouse.down()
        for x, y in points[1:]:
            page.mouse.move(box['x'] + x, box['y'] + y)
        page.mouse.up()

    def objects(self, page):
        return page.evaluate('Object.values(MB.board.page().objects)')

    def draw(self, page, *strokes):
        page.click('[data-tool="pen"]')
        before = page.evaluate('MB.board.canvas.getObjects().length')
        for points in strokes:
            self.stroke(page, points)
        page.wait_for_function(f'MB.board.canvas.getObjects().length === {before + len(strokes)}')

    def select_all(self, page):
        page.click('[data-tool="select"]')
        page.evaluate('MB.board.selectAll()')

    # ---------- Tracés bruts et lasso ----------
    def test_raw_ink_is_saved_and_lasso_selects_only_enclosed_items(self):
        with sync_playwright() as pw:
            browser = self.launch(pw)
            _, page = self.context(browser, self.teacher)
            self.open(page, self.document.pk)
            self.draw(page, polyline((100, 100), (180, 120)), polyline((110, 160), (190, 150)), polyline((420, 120), (500, 160)))
            self.wait_saved(page)
            saved = list(self.state(page, self.document.pk)['pages'][0]['objects'].values())
            ink = saved[0]['ink']
            self.assertEqual(len(ink['x']), len(ink['y']))
            self.assertEqual(len(ink['x']), len(ink['t']))
            self.assertGreater(len(ink['x']), 5)
            self.assertEqual(ink['width'], 3)
            # Lasso autour des deux premiers traits seulement.
            page.click('[data-tool="lasso"]')
            self.stroke(page, polyline((70, 70), (230, 70), (230, 200), (70, 200), (70, 75), steps=8))
            expect(page.locator('[data-tool="select"]')).to_have_class('mb-tool is-active')
            selected = page.evaluate('MB.board.selected().map(o => o.id).sort()')
            first_two = sorted(o['id'] for o in sorted(saved, key=lambda o: o['left'])[:2])
            self.assertEqual(selected, first_two)
            bar = page.locator('#mbSelectionBar')
            expect(bar.locator('[data-act="shape"]')).to_be_visible()
            expect(bar.locator('[data-act="to-text"]')).to_be_hidden()      # reconnaissance non configurée
            before = page.evaluate('MB.board.selected()[0].getBoundingRect().width')
            bar.locator('[data-act="bigger"]').click()
            self.wait_saved(page)
            self.assertGreater(page.evaluate(f"MB.board.byId['{first_two[0]}'].getBoundingRect().width"), before * 1.1)
            browser.close()
        self.assertEqual(self.errors, [])

    # ---------- Formes ----------
    def test_shape_recognition_on_imperfect_drawings(self):
        # Tracés « à main levée » : bruit régulier, extrémités qui ne se rejoignent pas tout à fait.
        def wobble(points, amp=2.5):
            return [{'x': x + amp * math.sin(i * 1.7), 'y': y + amp * math.cos(i * 2.3), 't': i * 12} for i, (x, y) in enumerate(points)]
        cases = {
            'line': polyline((10, 10), (300, 40)),
            'circle': circle(200, 200, 80, 48, 0.97),
            'ellipse': [(200 + 140 * math.cos(a), 200 + 70 * math.sin(a)) for a in [2 * math.pi * i / 48 * 0.97 for i in range(49)]],
            'triangle': polyline((100, 300), (250, 80), (400, 300), (110, 296)),
            'rectangle': polyline((50, 50), (350, 52), (348, 200), (52, 198), (50, 58)),
            'square': polyline((50, 50), (250, 50), (250, 250), (50, 250), (50, 58)),
            'arrow': polyline((40, 200), (340, 200), (300, 170), (340, 200), (300, 230), steps=10),
            'angle': polyline((300, 60), (80, 260), (360, 260)),
            'polygon': polyline((200, 40), (330, 130), (280, 280), (120, 280), (70, 130), (190, 46)),
        }
        scribbles = {
            'lettre S': [(300 - 60 * math.cos(t), 100 + 40 * math.sin(t) * (1 if t < math.pi else -1) + 25 * t) for t in [i / 10 for i in range(63)]],
            'zigzag': polyline((10, 10), (40, 80), (70, 10), (100, 80), (130, 10), (160, 80), steps=6),
            'petit point': polyline((10, 10), (14, 12)),
        }
        with sync_playwright() as pw:
            browser = self.launch(pw)
            _, page = self.context(browser, self.teacher)
            self.open(page, self.document.pk)
            page.wait_for_function('!!(MB.Ink && MB.Ink.recognizeShape)')
            found = {name: page.evaluate('(p) => { const s = MB.Ink.recognizeShape(p); return s && s.kind; }', wobble(points))
                     for name, points in cases.items()}
            missed = {name: page.evaluate('(p) => { const s = MB.Ink.recognizeShape(p); return s && s.kind; }', wobble(points, 1))
                      for name, points in scribbles.items()}
            browser.close()
        self.assertEqual(found, {name: name for name in cases})
        self.assertEqual(missed, {name: None for name in scribbles})

    def test_shapes_from_selection_and_automatic_mode_keep_the_original(self):
        with sync_playwright() as pw:
            browser = self.launch(pw)
            _, page = self.context(browser, self.teacher)
            self.open(page, self.document.pk)
            # Bouton « Forme » sur une sélection.
            self.draw(page, circle(220, 220, 70, 40, 0.98))
            self.select_all(page)
            page.locator('#mbSelectionBar [data-act="shape"]').click()
            page.wait_for_function("Object.values(MB.board.page().objects).some(o => o.ink_shape === 'circle')")
            shape = self.objects(page)[0]
            self.assertEqual((shape['type'], shape['ink_shape'], len(shape['ink_source'])), ('circle', 'circle', 1))
            self.assertAlmostEqual(shape['radius'], 70, delta=6)
            self.assertEqual(shape['ink_source'][0]['type'], 'path')
            self.assertNotIn('_by', shape['ink_source'][0])
            # « Écriture originale » rend le trait.
            self.select_all(page)
            restore = page.locator('#mbSelectionBar [data-act="restore"]')
            expect(restore).to_be_visible()
            restore.click()
            page.wait_for_function("Object.values(MB.board.page().objects).every(o => o.type === 'path')")
            self.assertEqual(len(self.objects(page)), 1)
            # Formes automatiques : le carré dessiné devient un carré ; Ctrl+Z rend le trait.
            page.click('[data-tool="pen"]')
            expect(page.locator('#mbToolOptions')).to_be_visible()
            page.locator('#mbAutoShapes').check()
            self.stroke(page, polyline((400, 100), (560, 100), (560, 260), (400, 260), (400, 106)))
            page.wait_for_function("Object.values(MB.board.page().objects).some(o => o.ink_shape === 'square')")
            square = next(o for o in self.objects(page) if o.get('ink_shape'))
            self.assertEqual(square['type'], 'rect')
            self.assertAlmostEqual(square['width'], square['height'], delta=1)
            # Petite écriture : jamais transformée (lettres, chiffres).
            self.stroke(page, circle(300, 400, 10, 20, 0.95))
            page.wait_for_timeout(300)
            self.assertEqual(sum(1 for o in self.objects(page) if o.get('ink_shape')), 1)
            page.keyboard.press('Escape')
            page.evaluate('MB.board.undo()')     # le petit « o »
            page.evaluate('MB.board.undo()')     # la forme automatique
            page.wait_for_function("!Object.values(MB.board.page().objects).some(o => o.ink_shape)")
            self.wait_saved(page)
            saved = self.state(page, self.document.pk)['pages'][0]['objects']
            browser.close()
        self.assertEqual(sorted(o['type'] for o in saved.values()), ['path', 'path'])
        self.assertEqual(self.errors, [])

    # ---------- Gomme intelligente ----------
    def test_smart_eraser_modes(self):
        with sync_playwright() as pw:
            browser = self.launch(pw)
            _, page = self.context(browser, self.teacher)
            self.open(page, self.document.pk)
            self.draw(page, polyline((100, 150), (500, 150), steps=40))
            page.evaluate("""() => Promise.all([
                MB.board.addModel({type: 'math', latex: 'x^2', color: '#212529', fontSize: 28, left: 120, top: 300}),
                MB.board.addModel({type: 'i-text', text: 'Bonjour', fontSize: 28, fill: '#212529', left: 360, top: 300})])""")
            page.wait_for_function('MB.board.canvas.getObjects().length === 3')
            page.click('[data-tool="eraser"]')
            expect(page.locator('#mbToolOptions')).to_be_visible()
            # Partie d'un trait : le trait est coupé en deux.
            page.locator('input[name="mbEraserMode"][value="stroke"]').check()
            self.stroke(page, polyline((300, 110), (300, 190), steps=10))
            page.wait_for_function("Object.values(MB.board.page().objects).filter(o => o.type === 'path').length === 2")
            pieces = sorted((o for o in self.objects(page) if o['type'] == 'path'), key=lambda o: o['left'])
            self.assertLess(pieces[0]['left'] + pieces[0]['width'], 300)
            self.assertGreater(pieces[1]['left'], 300)
            self.assertTrue(all(len(p['ink']['x']) >= 2 for p in pieces))
            # Formules seulement : le texte résiste, la formule part.
            page.locator('input[name="mbEraserMode"][value="math"]').check()
            box = page.locator('#mbCanvasHost').bounding_box()
            text = page.evaluate("MB.board.canvas.getObjects().find(o => o.type.toLowerCase() === 'i-text').getCenterPoint()")
            formula = page.evaluate("MB.board.canvas.getObjects().find(o => o.mb).getCenterPoint()")
            page.mouse.click(box['x'] + text['x'], box['y'] + text['y'])
            page.mouse.click(box['x'] + formula['x'], box['y'] + formula['y'])
            page.wait_for_function("!Object.values(MB.board.page().objects).some(o => o.type === 'math')")
            # Textes seulement.
            page.locator('input[name="mbEraserMode"][value="text"]').check()
            page.mouse.click(box['x'] + text['x'], box['y'] + text['y'])
            page.wait_for_function("!Object.values(MB.board.page().objects).some(o => o.type === 'i-text')")
            # Annuler : le texte, la formule, puis le trait entier reviennent.
            for _ in range(3):
                page.evaluate('MB.board.undo()')
            page.wait_for_function("Object.values(MB.board.page().objects).filter(o => o.type === 'path').length === 1")
            self.wait_saved(page)
            saved = self.state(page, self.document.pk)['pages'][0]['objects']
            browser.close()
        self.assertEqual(sorted(o['type'] for o in saved.values()), ['i-text', 'math', 'path'])
        self.assertEqual(self.errors, [])

    # ---------- Conversion texte / formule ----------
    def test_conversion_to_formula_and_text_keeps_the_handwriting(self):
        sent = []
        answers = {'math': {'latex': '\\frac{x^2-1}{x+1}'}, 'text': {'text': 'الدالة متزايدة'}}

        def recognize(route):
            body = json.loads(route.request.post_data)
            sent.append(body)
            route.fulfill(status=200, content_type='application/json', body=json.dumps(answers[body['kind']]))

        with override_settings(MATHBOARD_RECOGNITION='myscript', MYSCRIPT_APPLICATION_KEY='a', MYSCRIPT_HMAC_KEY='h'), \
                sync_playwright() as pw:
            browser = self.launch(pw)
            _, page = self.context(browser, self.teacher)
            page.route('**/api/documents/*/reconnaissance/', recognize)     # moteur simulé
            self.open(page, self.document.pk)
            self.draw(page, polyline((100, 100), (160, 140)), polyline((100, 140), (160, 100)))
            self.select_all(page)
            bar = page.locator('#mbSelectionBar')
            bar.locator('[data-act="to-math"]').click()
            field = page.locator('#mbConvMath')
            page.wait_for_function("document.getElementById('mbConvMath').value === '\\\\frac{x^2-1}{x+1}'")
            expect(page.locator('#mbConvAccept')).to_be_enabled()
            expect(page.locator('#mbConvLangRow')).to_be_hidden()
            # Correction dans MathLive, puis acceptation : l'écriture reste.
            page.evaluate("document.getElementById('mbConvMath').value = '\\\\frac{x^2-1}{x-1}'")
            page.locator('#mbConvAccept').click()
            page.wait_for_function("Object.values(MB.board.page().objects).some(o => o.type === 'math')")
            math_obj = next(o for o in self.objects(page) if o['type'] == 'math')
            self.assertEqual(math_obj['latex'], '\\frac{x^2-1}{x-1}')
            self.assertNotIn('ink_source', math_obj)
            self.assertEqual(sum(1 for o in self.objects(page) if o['type'] == 'path'), 2)
            # En texte (arabe), en remplaçant l'écriture : récupérable ensuite.
            page.click('[data-tool="lasso"]')
            self.stroke(page, polyline((80, 80), (190, 80), (190, 160), (80, 160), (80, 85), steps=6))
            bar.locator('[data-act="to-text"]').click()
            page.locator('#mbConvLang').select_option('ar')
            expect(page.locator('#mbConvText')).to_have_value('الدالة متزايدة')
            expect(page.locator('#mbConvText')).to_have_attribute('dir', 'rtl')
            page.locator('#mbConvReplace').check()
            page.locator('#mbConvAccept').click()
            page.wait_for_function("Object.values(MB.board.page().objects).some(o => o.type === 'i-text')")
            text_obj = next(o for o in self.objects(page) if o['type'] == 'i-text')
            self.assertEqual((text_obj['text'], text_obj['direction']), ('الدالة متزايدة', 'rtl'))
            self.assertEqual(len(text_obj['ink_source']), 2)
            self.assertFalse(any(o['type'] == 'path' for o in self.objects(page)))
            page.click('[data-tool="select"]')
            page.evaluate("MB.board.canvas.setActiveObject(MB.board.canvas.getObjects().find(o => o.type.toLowerCase() === 'i-text'))")
            page.evaluate("MB.board.ui.selection(MB.board.selected(), MB.board)")
            bar.locator('[data-act="restore"]').click()
            page.wait_for_function("Object.values(MB.board.page().objects).filter(o => o.type === 'path').length === 2")
            # Refuser : rien n'est ajouté.
            self.select_all(page)
            count = len(self.objects(page))
            bar.locator('[data-act="to-math"]').click()
            expect(page.locator('#mbConvAccept')).to_be_enabled()
            page.locator('#mbConvReject').click()
            self.assertEqual(len(self.objects(page)), count)
            browser.close()
        # Envoyé au serveur : les tracés bruts (x, y, t) seulement, sans image.
        self.assertEqual([b['kind'] for b in sent], ['math', 'text', 'text', 'math'])
        self.assertEqual([b['lang'] for b in sent[1:3]], ['fr_FR', 'ar'])
        stroke = sent[0]['strokes'][0]
        self.assertEqual(set(stroke), {'x', 'y', 't'})
        self.assertEqual(len(sent[0]['strokes']), 2)
        self.assertGreaterEqual(min(stroke['x']), 0)
        self.assertEqual(self.errors, [])
