from browser_tests.test_course_html import CourseHtmlBrowserTests as B
class P(B):
    def test_shots(self):
        page, _ = self.open(1280, 860)
        page.screenshot(path='/tmp/claude-1000/-home-abdo-Bureau-EduBac-C/39a85d2e-624c-4eab-9cd1-c0a068e0497c/scratchpad/n_desk1.png')
        page.select_option('#pageChapitre', 's3'); page.wait_for_timeout(500)
        page.screenshot(path='/tmp/claude-1000/-home-abdo-Bureau-EduBac-C/39a85d2e-624c-4eab-9cd1-c0a068e0497c/scratchpad/n_desk2.png')
        page.close()
        page, _ = self.open(390, 760, theme='dark')
        page.screenshot(path='/tmp/claude-1000/-home-abdo-Bureau-EduBac-C/39a85d2e-624c-4eab-9cd1-c0a068e0497c/scratchpad/n_ph1.png')
        page.select_option('#pageChapitre', 's8'); page.wait_for_timeout(500)
        page.screenshot(path='/tmp/claude-1000/-home-abdo-Bureau-EduBac-C/39a85d2e-624c-4eab-9cd1-c0a068e0497c/scratchpad/n_ph2.png')
        page.click('#pageNext'); page.wait_for_timeout(500)
        page.screenshot(path='/tmp/claude-1000/-home-abdo-Bureau-EduBac-C/39a85d2e-624c-4eab-9cd1-c0a068e0497c/scratchpad/n_ph3.png')
        print('suites', page.evaluate("document.querySelectorAll('.bloc.suite').length"), 'pages', page.evaluate("document.querySelectorAll('.feuille').length"))
        page.close()
del B
