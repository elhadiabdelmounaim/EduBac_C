"""Real-session coverage for the local whiteboard tools; no OCR or AI calls."""
import os
import shutil

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from accounts.models import TeacherProfile, User
from whiteboard.models import WhiteboardBoard


class WhiteboardToolsBrowserTests(StaticLiveServerTestCase):
    def test_draw_move_edit_and_reload(self):
        teacher = User.objects.create_user(
            username="board-tools-teacher", email="board-tools@example.test",
            password="Browser-test-only-123!", role="teacher",
        )
        TeacherProfile.objects.get_or_create(user=teacher)
        board = WhiteboardBoard.objects.create(
            created_by=teacher, title="Outils locaux",
            content={"version": 1, "objects": [
                {"id": "text-test", "type": "text", "text": "x + 2 = 5",
                 "x": 150, "y": 180, "size": 4, "color": "#1e2a4a"},
            ]},
        )
        path = reverse("whiteboard:room", args=[board.pk])
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                executable_path=os.environ.get("CHROMIUM_EXECUTABLE") or shutil.which("chromium"),
                headless=True, args=["--no-sandbox"],
            )
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 1050})
                # An old unversioned asset must never be requested after a UI update.
                page.route("**/static/js/whiteboard.js", lambda route: route.abort())
                page.route("**/static/js/whiteboard-objects.js", lambda route: route.abort())
                errors, external_recognition = [], []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("request", lambda request: external_recognition.append(request.url)
                        if "api.mathpix.com" in request.url else None)
                page.goto(self.live_server_url + reverse("accounts:login"))
                page.locator('input[name="email"]').fill(teacher.email)
                page.locator('input[name="password"]').fill("Browser-test-only-123!")
                page.get_by_role("button", name="Se connecter", exact=True).click()
                page.wait_for_url(lambda url: "/connexion/" not in url)
                page.goto(self.live_server_url + path)
                page.wait_for_function("window.EduBacBoard?.getObjects().length === 1")
                canvas = page.locator("#wbCanvas")
                box = canvas.bounding_box()
                scale = canvas.evaluate(
                    "el => ({x: el.getBoundingClientRect().width / el.width,"
                    "y: el.getBoundingClientRect().height / el.height})"
                )
                def point(x, y):
                    return box["x"] + x * scale["x"], box["y"] + y * scale["y"]
                # Drag an existing text object with the actual selection tool.
                page.locator('[data-tool="select"]').click()
                page.mouse.move(*point(170, 170))
                page.mouse.down()
                page.mouse.move(*point(240, 210), steps=8)
                page.mouse.up()
                page.wait_for_function("EduBacBoard.getObjects()[0].x > 150")
                moved = page.evaluate("EduBacBoard.getObjects()[0]")
                page.locator("#wbEditSelected").click()
                page.locator('#wbEditorFields [name="text"]').fill("الدالة f(x) = x²\nx + 2 = 5")
                page.locator('#wbEditorForm button[type="submit"]').click()
                expect(page.locator("#wbObjectEditor")).not_to_be_visible()
                page.wait_for_function("EduBacBoard.getObjects()[0].text.includes('الدالة')")
                # Draw a freehand stroke through pointer events.
                page.locator('[data-tool="pencil"]').click()
                page.mouse.move(*point(350, 250))
                page.mouse.down()
                page.mouse.move(*point(380, 270), steps=8)
                page.mouse.move(*point(425, 235), steps=8)
                page.mouse.up()
                page.wait_for_function("EduBacBoard.getObjects().length === 2")
                before = page.evaluate("EduBacBoard.getObjects()")
                self.assertEqual(before[1]["type"], "stroke")
                self.assertGreater(len(before[1]["points"]), 2)
                page.locator("#wbUndo").click()
                page.wait_for_function("EduBacBoard.getObjects().length === 1")
                page.locator("#wbRedo").click()
                page.wait_for_function("EduBacBoard.getObjects().length === 2")
                background = page.locator("#wbBackground")
                expect(background).to_have_value("grid")
                previews = set()
                for style in ("plain", "grid", "dots", "ruled"):
                    background.select_option(style)
                    self.assertEqual(page.evaluate("EduBacBoard.getObjects()"), before)
                    previews.add(canvas.evaluate("el => el.toDataURL()"))
                self.assertEqual(len(previews), 4, "Every paper style renders differently")
                with page.expect_response(
                    lambda response: response.url.endswith(f"/{board.pk}/api/")
                    and response.request.method == "POST" and response.ok
                ):
                    page.locator("#wbSaveBtn").click()
                page.reload()
                page.wait_for_function("window.EduBacBoard?.getObjects().length === 2")
                restored = page.evaluate("EduBacBoard.getObjects()")
                expect(page.locator("#wbBackground")).to_have_value("ruled")
                self.assertEqual(restored, before)
                self.assertEqual(restored[0]["x"], moved["x"])
                page.locator('[data-tool="text"]').click()
                page.mouse.click(*point(500, 320))
                expect(page.locator("#wbObjectEditor")).to_be_visible()
                page.locator('#wbEditorFields [name="text"]').fill("f(x) = x² + 1")
                page.locator('#wbEditorForm button[type="submit"]').click()
                page.wait_for_function("EduBacBoard.getObjects().length === 3")
                self.assertEqual(page.evaluate("EduBacBoard.getSelected().text"), "f(x) = x² + 1")
                for tool in ("pen", "highlighter", "eraser", "line", "arrow",
                             "rect", "circle", "triangle", "ruler", "protractor"):
                    count = page.evaluate("EduBacBoard.getObjects().length")
                    page.locator(f'[data-tool="{tool}"]').click()
                    expect(page.locator(f'[data-tool="{tool}"]')).to_have_attribute("aria-pressed", "true")
                    page.mouse.move(*point(350, 250))
                    page.mouse.down()
                    page.mouse.move(*point(425, 280), steps=6)
                    page.mouse.up()
                    page.wait_for_function(
                        "n => EduBacBoard.getObjects().length === n + 1", arg=count
                    )
                    if tool == "eraser":
                        self.assertTrue(page.evaluate("EduBacBoard.getObjects().at(-1).erase"))
                page.locator("#wbMathBtn").click()
                page.locator("#wbMathInput").fill("x^2 + 1")
                page.locator("#wbMathPlace").click()
                expect(page.locator("#wbMathModal")).not_to_be_visible()
                self.assertEqual(page.evaluate("EduBacBoard.getObjects().at(-1).type"), "math")
                self.assertEqual(external_recognition, [])
                self.assertEqual(errors, [])
                for width in (390, 1440):
                    page.set_viewport_size({"width": width, "height": 1050})
                    expect(canvas).to_be_visible()
                    self.assertTrue(page.evaluate(
                        "document.documentElement.scrollWidth <= innerWidth + 1"
                    ))
                os.makedirs("test-results/whiteboard", exist_ok=True)
                page.screenshot(path="test-results/whiteboard/local-tools.jpg", full_page=True)
            finally:
                browser.close()
