"""Messagerie dans un vrai navigateur : modération, LaTeX, contexte, repli sans WebSocket.

Le serveur de test est WSGI : aucun WebSocket n'est disponible, ce qui vérifie
aussi le repli automatique sur l'interrogation périodique.
"""
import os
import shutil

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.servers.basehttp import WSGIServer
from django.test.testcases import LiveServerThread
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from accounts.models import User
from chat.models import ChatMessage, ChatReport, PrivateMessage
from classrooms.models import Classroom, ClassroomMember
from education.models import Course, Lesson

PASSWORD = 'Browser-test-only-123!'


class _SingleThreadWSGIServer(WSGIServer):
    def __init__(self, *args, connections_override=None, **kwargs):
        # Le fil du serveur partage déjà les connexions de test (LiveServerThread.run).
        super().__init__(*args, **kwargs)


class SingleThreadLiveServer(LiveServerThread):
    """Traite les requêtes une par une.

    La base de test SQLite en mémoire est partagée entre les fils du serveur
    multithread : des requêtes simultanées (présence, messages, membres) peuvent
    y perdre la session. La messagerie émet justement des requêtes parallèles.
    """
    server_class = _SingleThreadWSGIServer


class ChatModerationBrowserTests(StaticLiveServerTestCase):
    server_thread_class = SingleThreadLiveServer

    def setUp(self):
        self.teacher = User.objects.create_user(
            username='chat-prof', email='chat-prof@example.test', password=PASSWORD,
            role='teacher', first_name='Nadia', last_name='Prof',
        )
        self.student = User.objects.create_user(
            username='chat-eleve', email='chat-eleve@example.test', password=PASSWORD,
            role='student', first_name='Omar', last_name='Élève',
        )
        self.classroom = Classroom.objects.create(name='TC-Chat', niveau='tronc_commun', teacher=self.teacher)
        ClassroomMember.objects.create(classroom=self.classroom, user=self.student)
        course = Course.objects.create(name='Mathématiques', niveau='tronc_commun', order=1)
        self.lesson = Lesson.objects.create(course=course, order=1, title='Les ensembles', content='…')

    def login(self, page, user):
        page.goto(self.live_server_url + reverse('accounts:login'))
        page.locator('input[name="username"]').fill(user.username)
        page.locator('input[name="password"]').fill(PASSWORD)
        page.locator('form button[type="submit"]').first.click()
        page.wait_for_url(lambda url: '/connexion/' not in url)

    def test_class_chat_moderation_and_consultation_context(self):
        room_url = self.live_server_url + reverse('chat:room', args=[self.classroom.pk])
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                executable_path=os.environ.get('CHROMIUM_EXECUTABLE') or shutil.which('chromium'),
                headless=True, args=['--no-sandbox'],
            )
            try:
                errors = []
                teacher_ctx = browser.new_context(viewport={'width': 1280, 'height': 900})
                student_ctx = browser.new_context(viewport={'width': 390, 'height': 844})
                teacher = teacher_ctx.new_page()
                student = student_ctx.new_page()
                for page in (teacher, student):
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.on('dialog', lambda dialog: dialog.accept(
                        'Correction : $x^3$' if dialog.type == 'prompt' else None,
                    ))

                # Le professeur écrit une formule : KaTeX la met en forme.
                self.login(teacher, self.teacher)
                teacher.goto(room_url)
                teacher.locator('#chatInput').fill('Formule du jour : $x^2+1$')
                teacher.locator('#chatInput').press('Enter')
                expect(teacher.locator('.chat-bubble .katex').first).to_be_visible()

                # Il passe le salon en mode annonces.
                teacher.locator('#chatSettingsBtn').click()
                teacher.locator('#chatSettingsDialog input[name="is_locked"]').check()
                teacher.locator('#chatSettingsDialog button[type="submit"]').click()
                expect(teacher.locator('#chatSettingsDialog')).not_to_be_visible()

                # L'élève (mobile) voit le message mais ne peut pas écrire.
                self.login(student, self.student)
                student.goto(room_url)
                expect(student.locator('.chat-bubble .katex').first).to_be_visible()
                expect(student.locator('#chatRestriction')).to_contain_text('réservé ce salon')
                expect(student.locator('#chatInput')).to_be_disabled()

                # Il signale le message du professeur.
                student.locator('.chat-bubble-row.theirs .chat-act-report').first.click()
                student.locator('.chat-report-dialog input[value="other"]').check()
                student.locator('.chat-report-dialog button[type="submit"]').click()
                expect(student.locator('.chat-report-dialog')).not_to_be_visible()

                # Le professeur rouvre le salon ; l'élève le voit sans recharger (repli 3 s).
                teacher.locator('#chatSettingsBtn').click()
                teacher.locator('#chatSettingsDialog input[name="is_locked"]').uncheck()
                teacher.locator('#chatSettingsDialog button[type="submit"]').click()
                expect(student.locator('#chatInput')).to_be_enabled(timeout=10000)

                # L'élève écrit, corrige (fenêtre de 5 min) puis supprime son message.
                student.locator('#chatInput').fill('Je n’ai pas compris')
                student.locator('#chatInput').press('Enter')
                mine = student.locator('.chat-bubble-row.mine').last
                expect(mine).to_contain_text('Je n’ai pas compris')
                mine.locator('.chat-act-edit').click()
                expect(mine.locator('.katex')).to_be_visible()
                expect(mine).to_contain_text('modifié')
                # Le professeur reçoit la correction sans recharger la page.
                expect(teacher.locator('.chat-bubble-row.theirs').last).to_contain_text('modifié', timeout=10000)
                student.locator('.chat-bubble-row.mine').last.locator('.chat-act-delete').click()
                expect(student.locator('.chat-bubble-row.mine').last).to_contain_text('Message supprimé')
                expect(teacher.locator('.chat-bubble-row.theirs').last).to_contain_text(
                    'Message supprimé', timeout=10000,
                )

                # Consultation : l'élève lie sa question à une leçon.
                student.goto(self.live_server_url + reverse(
                    'chat:private_student_chat', args=[self.classroom.pk],
                ))
                student.locator('#privateContextSelect').select_option(f'lesson:{self.lesson.pk}')
                student.locator('#chatInput').fill('Que veut dire $A \\subset B$ ?')
                student.locator('#chatInput').press('Enter')
                expect(student.locator('.chat-context-card')).to_contain_text('Les ensembles')
                expect(student.locator('#privateChatMessages .katex').first).to_be_visible()

                # Le professeur voit le bouton de brouillon IA (sans l'appeler).
                teacher.goto(self.live_server_url + reverse('chat:home') + '?tab=individuals')
                teacher.goto(self.live_server_url + reverse(
                    'chat:teacher_consult_student', args=[self.student.pk],
                ))
                expect(teacher.locator('#privateAiDraftBtn')).to_be_visible()
                expect(teacher.locator('.chat-context-card')).to_contain_text('Les ensembles')

                # Le signalement vise le professeur : il est réservé à l'administration.
                teacher.goto(self.live_server_url + reverse('chat:moderation'))
                expect(teacher.locator('.moderation-page')).to_contain_text('Aucun signalement')

                self.assertEqual(errors, [])
            finally:
                browser.close()
        # Vérifications en base une fois le navigateur fermé (connexion partagée).
        self.assertEqual(ChatReport.objects.count(), 1)
        self.assertTrue(ChatMessage.objects.get(sender=self.student).is_deleted)
        self.assertEqual(PrivateMessage.objects.get().lesson, self.lesson)
