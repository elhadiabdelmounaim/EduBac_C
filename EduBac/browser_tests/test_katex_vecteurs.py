"""Formules KaTeX des quiz : la flèche de \\vec (dessinée en SVG) reste visible malgré la règle
responsive `svg { max-width: 100% }` ; l'explication montre la règle du cours puis la solution."""
import json
import os
import shutil

from django.conf import settings
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from playwright.sync_api import sync_playwright

from accounts.models import User
from education.models import Course, Lesson
from quizzes.json_import import create_quiz_from_json


class KatexVecteursBrowserTests(StaticLiveServerTestCase):
    def setUp(self):
        self.prof = User.objects.create_user(username='prof', email='prof@example.test', role='teacher')
        cours = Course.objects.create(name='Mathématiques', niveau='1ere_bac_sc')
        lecon = Lesson.objects.create(course=cours, title='Le produit scalaire', order=4, content='')
        question = {
            'id': 'Q1', 'type': 'multiple_choice',
            'statement': r'Calculer $\vec u\cdot\vec v$ si $\|\vec u\|=2$, $\|\vec v\|=3$ et l’angle vaut $\frac{\pi}{3}$.',
            'choices': [{'id': k, 'text': t} for k, t in (('A', '$6$'), ('B', '$3$'), ('C', '$0$'), ('D', '$1$'))],
            'correct_answer': 'B', 'difficulty': 'easy', 'points': 1,
            'explication': {
                'regle': r'$\vec u\cdot\vec v=\|\vec u\|\times\|\vec v\|\times\cos(\vec u,\vec v)$.',
                'solution': r'$2\times3\times\frac12=3$.',
            },
        }
        contenu = json.dumps({'quiz': {'title': 'Vecteurs', 'questions': [question]}}).encode()
        self.quiz = create_quiz_from_json(SimpleUploadedFile('q.json', contenu), self.prof, selected_lesson=lecon)
        session = SessionStore()
        session['user_id'] = self.prof.pk
        session['role'] = self.prof.role
        session['password_session_version'] = self.prof.password_session_version
        session.save()
        self.session_key = session.session_key
        self.playwright = sync_playwright().start()
        executable = os.environ.get('CHROMIUM_EXECUTABLE') or shutil.which('chromium')
        self.browser = self.playwright.chromium.launch(executable_path=executable, headless=True, args=['--no-sandbox'])

    def tearDown(self):
        self.browser.close()
        self.playwright.stop()
        super().tearDown()

    def test_fleches_des_vecteurs_et_explication(self):
        for largeur in (1100, 390):
            with self.subTest(largeur=largeur):
                contexte = self.browser.new_context(viewport={'width': largeur, 'height': 900})
                contexte.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': self.session_key,
                                       'url': self.live_server_url}])
                page = contexte.new_page()
                page.route('https://fonts.googleapis.com/**', lambda route: route.abort())
                page.route('https://fonts.gstatic.com/**', lambda route: route.abort())
                page.goto(f"{self.live_server_url}{reverse('quizzes:teacher_ai')}?quiz={self.quiz.pk}")
                page.wait_for_selector('.quiz-explication .katex', timeout=15000)
                largeurs = page.evaluate(
                    "[...document.querySelectorAll('.katex .overlay svg')].map(s => s.getBoundingClientRect().width)")
                self.assertTrue(largeurs, 'aucune flèche de vecteur rendue')
                self.assertTrue(all(w > 2 for w in largeurs), f'flèches écrasées : {largeurs}')
                ordre = page.evaluate(
                    "[...document.querySelectorAll('.quiz-explication__bloc')].map(b => b.querySelector('strong').textContent.trim())")
                self.assertEqual(ordre, ['Règle du cours', 'Solution'])
                contexte.close()
