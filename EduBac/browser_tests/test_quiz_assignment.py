"""Parcours complet : import JSON → brouillon → modification → choix de la classe
→ confirmation → quiz chez les élèves de cette classe seulement → notifications.

Captures facultatives : CHAT_SCREENSHOT_DIR=/dossier.
"""
import json
import os
import re
import shutil

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from accounts.models import User
from classrooms.models import Classroom
from education.models import Course, Lesson
from notifications.models import Notification
from quizzes.models import Quiz, QuizAssignment

from .test_chat_moderation import PASSWORD, SingleThreadLiveServer


def question(qid, statement, correct, points):
    return {
        'id': qid, 'type': 'multiple_choice', 'statement': statement, 'correct_answer': correct,
        'difficulty': 'medium', 'points': points,
        'choices': [{'id': 'A', 'text': '1'}, {'id': 'B', 'text': '2'},
                    {'id': 'C', 'text': '3'}, {'id': 'D', 'text': '4'}],
    }


class QuizAssignmentJourneyTests(StaticLiveServerTestCase):
    server_thread_class = SingleThreadLiveServer

    def setUp(self):
        def user(username, first, role='student'):
            return User.objects.create_user(
                username=username, email=f'{username}@example.test', password=PASSWORD,
                role=role, first_name=first, last_name='Test')

        self.teacher = user('qa-prof', 'Nadia', 'teacher')
        self.omar, self.salma = user('qa-omar', 'Omar'), user('qa-salma', 'Salma')
        self.yassine, self.lina = user('qa-yassine', 'Yassine'), user('qa-lina', 'Lina')
        self.course = Course.objects.create(name='Mathématiques', niveau='tronc_commun')
        self.lesson = Lesson.objects.create(course=self.course, title='Équations du premier degré', order=1)
        self.target = Classroom.objects.create(name='TC A', niveau='tronc_commun', teacher=self.teacher)
        self.target.add_member(self.omar)
        self.target.add_member(self.salma)
        self.other = Classroom.objects.create(name='TC B', niveau='tronc_commun', teacher=self.teacher)
        self.other.add_member(self.yassine)
        self.other_level = Classroom.objects.create(name='1BAC SM', niveau='1ere_bac_sm', teacher=self.teacher)
        self.other_level.add_member(self.lina)
        self.empty = Classroom.objects.create(name='TC vide', niveau='tronc_commun', teacher=self.teacher)
        self.document = {'quiz': {
            'title': 'Équations — import', 'level': 'TCS', 'lesson': self.lesson.title, 'duration': 10,
            'questions': [question('Q1', 'Résoudre $x + 1 = 3$.', 'B', 2),
                          question('Q2', 'Résoudre $2x = 6$.', 'C', 3)],
        }}

    def shot(self, page, name):
        folder = os.environ.get('CHAT_SCREENSHOT_DIR')
        if folder:
            page.screenshot(path=os.path.join(folder, f'quiz-{name}.png'), full_page=True)

    def login(self, browser, username):
        context = browser.new_context(viewport={'width': 1280, 'height': 960})
        page = context.new_page()
        page.on('pageerror', lambda error: self.errors.append(f'{username}: {error}'))
        page.goto(self.live_server_url + reverse('accounts:login'))
        page.locator('[name="username"]').fill(username)
        page.locator('[name="password"]').fill(PASSWORD)
        page.locator('form button[type="submit"]').first.click()
        page.wait_for_url(lambda url: '/connexion/' not in url)
        return page

    def test_import_edit_choose_class_confirm_and_only_that_class_receives_it(self):
        self.errors = []
        base = self.live_server_url
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                executable_path=os.environ.get('CHROMIUM_EXECUTABLE') or shutil.which('chromium'),
                headless=True, args=['--no-sandbox'])
            try:
                # 1. Import du fichier JSON.
                teacher = self.login(browser, 'qa-prof')
                teacher.goto(base + reverse('quizzes:teacher_ai'))
                teacher.locator('#quizLevel').select_option('tronc_commun')
                teacher.locator('#quizCourse').select_option(str(self.course.pk))
                teacher.locator('#quizLesson').select_option(str(self.lesson.pk))
                teacher.locator('#quizJsonFile').set_input_files({
                    'name': 'quiz.json', 'mimeType': 'application/json',
                    'buffer': json.dumps(self.document, ensure_ascii=False).encode('utf-8')})
                teacher.get_by_role('button', name='Valider et créer le brouillon').click()
                teacher.wait_for_url(re.compile(r'\?quiz=\d+$'))
                quiz_id = int(re.search(r'\?quiz=(\d+)$', teacher.url).group(1))

                # 2. Consultation puis modification du brouillon.
                expect(teacher.locator('#quiz-preview-title')).to_have_text('Équations — import')
                expect(teacher.locator('.qb-detail-list > li')).to_have_count(2)
                teacher.get_by_role('link', name='Modifier le quiz').click()
                teacher.locator('#quizTitle').fill('Équations du premier degré — séance 1')
                teacher.get_by_role('button', name='Enregistrer').click()
                teacher.wait_for_url(re.compile(r'\?quiz=\d+$'))
                expect(teacher.locator('#quiz-preview-title')).to_have_text('Équations du premier degré — séance 1')

                # 3. Toutes les classes de l'enseignant, avec niveau et nombre d'élèves.
                cards = teacher.locator('#classroomChoices .qb-class-card')
                expect(cards).to_have_count(4)
                card = lambda classroom: teacher.locator(f'#classroomChoices label:has(input[value="{classroom.pk}"])')
                expect(card(self.target)).to_contain_text('Tronc Commun')
                expect(card(self.target).locator('.qb-class-count')).to_contain_text('2')
                expect(card(self.other).locator('.qb-class-count')).to_contain_text('1')
                expect(card(self.other_level)).to_contain_text('Autre niveau')
                expect(card(self.empty)).to_contain_text('Aucun élève inscrit')
                expect(card(self.other_level).locator('input')).to_be_disabled()
                expect(card(self.empty).locator('input')).to_be_disabled()
                summary = teacher.locator('.qb-assign-summary')
                expect(summary).to_contain_text('Équations du premier degré — séance 1')
                expect(summary).to_contain_text('Brouillon, pas encore envoyé')
                expect(summary.locator('div', has_text='Points')).to_contain_text('5')

                # 4. Sélection de la classe destinataire.
                card(self.target).click()
                expect(card(self.target).locator('input')).to_be_checked()
                self.shot(teacher, 'assign')

                # 5. Confirmation : l'annulation n'envoie rien, la confirmation affecte.
                teacher.get_by_role('button', name='Affecter le quiz à cette classe').click()
                dialog = teacher.locator('#assignConfirm')
                expect(dialog).to_be_visible()
                expect(dialog).to_contain_text('TC A')
                expect(dialog).to_contain_text('2 élèves')
                self.shot(teacher, 'confirm')
                dialog.get_by_role('button', name='Annuler').click()
                expect(dialog).to_be_hidden()
                teacher.wait_for_timeout(300)
                self.assertEqual(teacher.url.count('?quiz='), 1, 'annuler ne quitte pas la page')
                teacher.get_by_role('button', name='Affecter le quiz à cette classe').click()
                dialog.get_by_role('button', name='Confirmer l’affectation').click()
                teacher.wait_for_url(base + reverse('quizzes:manage'))
                expect(teacher.locator('.alert-success')).to_contain_text('TC A')

                # 6. Le quiz apparaît chez les élèves de la classe, avec une notification.
                for username in ('qa-omar', 'qa-salma'):
                    student = self.login(browser, username)
                    expect(student.locator('#notifBadge')).to_have_text('1', timeout=10000)
                    student.locator('#notifBellBtn').click()
                    expect(student.locator('#notifList')).to_contain_text('Nouveau quiz assigné')
                    student.goto(base + reverse('quizzes:assigned'))
                    expect(student.locator('main h2', has_text='Équations du premier degré — séance 1')).to_be_visible()
                    student.goto(base + reverse('quizzes:detail', args=[quiz_id]))
                    expect(student.get_by_role('heading', name='Équations du premier degré — séance 1')).to_be_visible()
                    if username == 'qa-omar':
                        self.shot(student, 'student')

                # 7. Les élèves des autres classes n'y ont pas accès.
                for username in ('qa-yassine', 'qa-lina'):
                    outsider = self.login(browser, username)
                    outsider.goto(base + reverse('quizzes:assigned'))
                    expect(outsider.locator('main h2', has_text='Équations du premier degré — séance 1')).to_have_count(0)
                    expect(outsider.locator('#notifBadge')).to_be_hidden()
                    outsider.goto(base + reverse('quizzes:detail', args=[quiz_id]))
                    self.assertIn(reverse('quizzes:assigned'), outsider.url)
                    response = outsider.goto(base + reverse('quizzes:start', args=[quiz_id]))
                    self.assertNotRegex(outsider.url, r'/quizzes/tentative/\d+/$')
                    self.assertLess(response.status, 500)
                self.assertEqual(self.errors, [])
            finally:
                browser.close()

        # Enregistrement en base : publication, classe et affectations exactes.
        quiz = Quiz.objects.get(pk=quiz_id)
        self.assertEqual(quiz.status, 'published')
        self.assertEqual(quiz.classroom, self.target)
        self.assertEqual(quiz.title, 'Équations du premier degré — séance 1')
        self.assertEqual(
            set(QuizAssignment.objects.filter(quiz=quiz).values_list('student__username', flat=True)),
            {'qa-omar', 'qa-salma'})
        # 8. Notifications « nouveau quiz » : uniquement pour la classe choisie.
        notified = set(Notification.objects.filter(title='Nouveau quiz assigné').values_list(
            'recipient__username', flat=True))
        self.assertEqual(notified, {'qa-omar', 'qa-salma'})

    def test_class_chosen_in_the_import_form_receives_the_quiz(self):
        self.errors = []
        base = self.live_server_url
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                executable_path=os.environ.get('CHROMIUM_EXECUTABLE') or shutil.which('chromium'),
                headless=True, args=['--no-sandbox'])
            try:
                teacher = self.login(browser, 'qa-prof')
                teacher.goto(base + reverse('quizzes:teacher_ai'))
                target = teacher.locator('#quizTargetClass')
                teacher.locator('#quizLevel').select_option('tronc_commun')
                # Seules les classes du niveau choisi sont proposées.
                options = target.locator('option:not([disabled]):not([value=""])')
                expect(options).to_have_count(3)
                expect(target.locator(f'option[value="{self.other_level.pk}"]')).to_be_disabled()
                target.select_option(str(self.other.pk))
                teacher.locator('#quizCourse').select_option(str(self.course.pk))
                teacher.locator('#quizLesson').select_option(str(self.lesson.pk))
                teacher.locator('#quizJsonFile').set_input_files({
                    'name': 'quiz.json', 'mimeType': 'application/json',
                    'buffer': json.dumps(self.document, ensure_ascii=False).encode('utf-8')})
                teacher.get_by_role('button', name='Valider et créer le brouillon').click()
                teacher.wait_for_url(re.compile(r'\?quiz=\d+$'))
                quiz_id = int(re.search(r'\?quiz=(\d+)$', teacher.url).group(1))
                expect(teacher.locator('.alert-success')).to_contain_text('Brouillon créé pour la classe TC B')

                # Raccourci vers l'envoi : la classe choisie est déjà sélectionnée.
                teacher.get_by_role('link', name='Confirmer l’envoi à TC B').click()
                expect(teacher.locator(f'#classroomChoices input[value="{self.other.pk}"]')).to_be_checked()
                teacher.get_by_role('button', name='Affecter le quiz à cette classe').click()
                expect(teacher.locator('#assignConfirm')).to_contain_text('TC B')
                teacher.locator('#assignConfirm').get_by_role('button', name='Confirmer l’affectation').click()
                # Le navigateur garde l'ancre #quizAssign après la redirection.
                teacher.wait_for_url(re.compile(re.escape(base + reverse('quizzes:manage')) + r'(#.*)?$'))
                expect(teacher.locator('.alert-success')).to_contain_text('envoyé à la classe TC B')

                yassine = self.login(browser, 'qa-yassine')
                expect(yassine.locator('#notifBadge')).to_have_text('1', timeout=10000)
                yassine.goto(base + reverse('quizzes:assigned'))
                expect(yassine.locator('main h2', has_text='Équations — import')).to_be_visible()
                omar = self.login(browser, 'qa-omar')
                omar.goto(base + reverse('quizzes:assigned'))
                expect(omar.locator('main h2', has_text='Équations — import')).to_have_count(0)
                omar.goto(base + reverse('quizzes:detail', args=[quiz_id]))
                self.assertIn(reverse('quizzes:assigned'), omar.url)

                # « Mes quiz » : un brouillon avec classe s'envoie à cette classe, sans en changer.
                teacher.goto(base + reverse('quizzes:manage'))
                expect(teacher.locator('.quiz-row-class', has_text='TC B').first).to_be_visible()
                self.assertEqual(self.errors, [])
            finally:
                browser.close()
        quiz = Quiz.objects.get(pk=quiz_id)
        self.assertEqual(quiz.classroom, self.other)
        self.assertEqual(list(QuizAssignment.objects.filter(quiz=quiz).values_list('student__username', flat=True)),
                         ['qa-yassine'])

    def test_one_page_import_and_send(self):
        self.errors = []
        base = self.live_server_url
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                executable_path=os.environ.get('CHROMIUM_EXECUTABLE') or shutil.which('chromium'),
                headless=True, args=['--no-sandbox'])
            try:
                teacher = self.login(browser, 'qa-prof')
                teacher.goto(base + reverse('quizzes:teacher_ai'))
                # 1. La classe d'abord : le niveau et le cours se remplissent seuls.
                teacher.locator('#quizTargetClass').select_option(str(self.target.pk))
                expect(teacher.locator('#quizLevel')).to_have_value('tronc_commun')
                expect(teacher.locator('#quizCourse')).to_have_value(str(self.course.pk))
                teacher.locator('#quizLesson').select_option(str(self.lesson.pk))
                teacher.locator('#secondsPerQuestion').fill('40')
                teacher.locator('#importDeadline').fill('2030-06-01T18:00')
                teacher.locator('#quizJsonFile').set_input_files({
                    'name': 'equations.json', 'mimeType': 'application/json',
                    'buffer': json.dumps(self.document, ensure_ascii=False).encode('utf-8')})
                expect(teacher.locator('#quizFileName')).to_contain_text('equations.json')
                self.shot(teacher, 'one-page')
                # 2. Un clic, une confirmation, et c'est envoyé.
                teacher.get_by_role('button', name='Importer et envoyer à la classe').click()
                dialog = teacher.locator('#importConfirm')
                expect(dialog).to_contain_text('TC A')
                expect(dialog).to_contain_text('2 élèves')
                self.shot(teacher, 'one-page-confirm')
                dialog.get_by_role('button', name='Importer et envoyer').click()
                teacher.wait_for_url(re.compile(re.escape(base + reverse('quizzes:manage')) + r'(#.*)?$'))
                expect(teacher.locator('.alert-success')).to_contain_text('envoyé à la classe TC A : 2 élève(s) notifié(s)')

                omar = self.login(browser, 'qa-omar')
                expect(omar.locator('#notifBadge')).to_have_text('1', timeout=10000)
                omar.goto(base + reverse('quizzes:assigned'))
                expect(omar.locator('main h2', has_text='Équations — import')).to_be_visible()
                yassine = self.login(browser, 'qa-yassine')
                yassine.goto(base + reverse('quizzes:assigned'))
                expect(yassine.locator('main h2', has_text='Équations — import')).to_have_count(0)
                self.assertEqual(self.errors, [])
            finally:
                browser.close()
        quiz = Quiz.objects.get()
        self.assertEqual((quiz.status, quiz.classroom, quiz.seconds_per_question), ('published', self.target, 40))
        self.assertEqual(set(QuizAssignment.objects.values_list('student__username', flat=True)), {'qa-omar', 'qa-salma'})

    def test_send_without_file_explains_and_works_on_older_browsers(self):
        self.errors = []
        base = self.live_server_url
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                executable_path=os.environ.get('CHROMIUM_EXECUTABLE') or shutil.which('chromium'),
                headless=True, args=['--no-sandbox'])
            try:
                teacher = self.login(browser, 'qa-prof')
                # Ancien Safari (iPhone) : ni requestSubmit, ni event.submitter.
                teacher.add_init_script("""
                    delete HTMLFormElement.prototype.requestSubmit;
                    Object.defineProperty(SubmitEvent.prototype, 'submitter', { get() { return undefined; } });
                """)
                teacher.goto(base + reverse('quizzes:teacher_ai'))
                teacher.locator('#quizTargetClass').select_option(str(self.target.pk))
                teacher.locator('#quizLesson').select_option(str(self.lesson.pk))
                # Sans fichier : un message clair, pas un clic sans effet.
                teacher.locator('#importSendBtn').click()
                expect(teacher.locator('#quizImportError')).to_be_visible()
                expect(teacher.locator('#quizImportError')).to_contain_text('le fichier JSON du quiz')
                expect(teacher.locator('.qi-drop')).to_have_class(re.compile('is-invalid'))
                self.assertTrue(teacher.url.endswith(reverse('quizzes:teacher_ai')))  # rien n'a été envoyé
                teacher.locator('#quizJsonFile').set_input_files({
                    'name': 'equations.json', 'mimeType': 'application/json',
                    'buffer': json.dumps(self.document, ensure_ascii=False).encode('utf-8')})
                expect(teacher.locator('#quizImportError')).to_be_hidden()
                teacher.locator('#importSendBtn').click()
                teacher.locator('#importConfirm').get_by_role('button', name='Importer et envoyer').click()
                teacher.wait_for_url(re.compile(re.escape(base + reverse('quizzes:manage')) + r'(#.*)?$'))
                expect(teacher.locator('.alert-success')).to_contain_text('envoyé à la classe TC A : 2 élève(s) notifié(s)')
                # Le bouton « brouillon » ne déclenche pas l'envoi.
                teacher.goto(base + reverse('quizzes:teacher_ai'))
                teacher.locator('#quizTargetClass').select_option(str(self.target.pk))
                teacher.locator('#quizLesson').select_option(str(self.lesson.pk))
                teacher.locator('#quizJsonFile').set_input_files({
                    'name': 'equations.json', 'mimeType': 'application/json',
                    'buffer': json.dumps(self.document, ensure_ascii=False).encode('utf-8')})
                teacher.locator('#importDraftBtn').click()
                teacher.wait_for_url(re.compile(r'\?quiz=\d+'))
                self.assertEqual(self.errors, [])
            finally:
                browser.close()
        self.assertEqual(sorted(Quiz.objects.values_list('status', flat=True)), ['draft', 'published'])
