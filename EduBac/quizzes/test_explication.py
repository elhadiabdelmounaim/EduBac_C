"""Explication en deux temps dans le JSON des quiz : « regle » (la règle du cours) puis
« solution ». L'ancien champ « explanation » (texte) reste accepté."""
import html as html_mod
import json

from django.core.files.uploadedfile import SimpleUploadedFile
from django.template.loader import render_to_string
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from education.models import Course, Lesson
from .json_import import QuizImportError, create_quiz_from_json
from .models import Question

REGLE = "Pour calculer l'image de $a$ par $f$, on remplace $x$ par $a$."
SOLUTION = r"$f(2)=2\times 2+3=7$. La bonne réponse est B."


def fichier(**champs):
    question = {
        'id': 'Q001', 'type': 'multiple_choice', 'statement': 'Soit $f(x)=2x+3$. Calculer $f(2)$.',
        'choices': [{'id': k, 'text': t} for k, t in (('A', '5'), ('B', '7'), ('C', '8'), ('D', '6'))],
        'correct_answer': 'B', 'difficulty': 'easy', 'points': 1, **champs,
    }
    contenu = json.dumps({'quiz': {'title': 'Fonctions', 'level': 'TCS', 'lesson': 'Les fonctions',
                                   'questions': [question]}}, ensure_ascii=False)
    return SimpleUploadedFile('quiz.json', contenu.encode('utf-8'), content_type='application/json')


class ExplicationJsonTests(TestCase):
    def setUp(self):
        self.prof = User.objects.create_user(username='prof', email='p@x.test', role='teacher')
        course = Course.objects.create(name='Mathématiques', niveau='tronc_commun')
        Lesson.objects.create(course=course, title='Les fonctions', order=1, content='')

    def importer(self, **champs):
        return create_quiz_from_json(fichier(**champs), self.prof).questions.get()

    def test_regle_puis_solution_importees(self):
        q = self.importer(explication={'regle': REGLE, 'solution': SOLUTION})
        self.assertEqual(q.regle, REGLE)
        self.assertEqual(q.explanation, SOLUTION)

    def test_regle_avec_accent_acceptee(self):
        q = self.importer(explication={'règle': REGLE, 'solution': SOLUTION})
        self.assertEqual(q.regle, REGLE)

    def test_ancien_champ_explanation_toujours_accepte(self):
        q = self.importer(explanation='$2\\times2+3=7$.')
        self.assertEqual((q.regle, q.explanation), ('', '$2\\times2+3=7$.'))
        self.assertEqual(self.importer().regle, '')          # sans explication : toujours accepté

    def test_erreurs_claires(self):
        cas = [
            ({'explication': {'solution': SOLUTION}}, 'la règle de l’explication est manquante'),
            ({'explication': {'regle': REGLE, 'solution': '  '}}, 'la solution de l’explication est manquante'),
            ({'explication': 'Un simple texte'}, 'doit contenir « regle »'),
            ({'explication': {'regle': REGLE, 'solution': SOLUTION, 'astuce': 'x'}}, 'accepte seulement'),
            ({'explication': {'regle': REGLE, 'règle': REGLE, 'solution': SOLUTION}}, 'est répétée'),
            ({'explication': {'regle': REGLE, 'solution': SOLUTION}, 'explanation': 'x'}, 'pas les deux'),
            ({'explication': {'regle': 12, 'solution': SOLUTION}}, 'la règle de l’explication'),
        ]
        for champs, message in cas:
            with self.subTest(message=message), self.assertRaisesMessage(QuizImportError, message):
                self.importer(**champs)
        self.assertFalse(Question.objects.exists())

    def test_affichage_regle_puis_solution(self):
        html = render_to_string('quizzes/_explication.html', {'regle': REGLE, 'solution': SOLUTION})
        self.assertIn('Règle du cours', html)
        self.assertIn('Solution', html)
        self.assertLess(html.index('data-explication-regle'), html.index('data-explication-solution'))
        # Ancienne question : un seul bloc « Explication ».
        ancien = render_to_string('quizzes/_explication.html', {'regle': '', 'solution': SOLUTION})
        self.assertNotIn('Règle du cours', ancien)
        self.assertIn('Explication', ancien)
        self.assertEqual(render_to_string('quizzes/_explication.html', {}).strip(), '')

    def test_modification_et_format_affiche(self):
        q = self.importer(explication={'regle': REGLE, 'solution': SOLUTION})
        session = self.client.session
        session['user_id'] = self.prof.pk
        session['role'] = self.prof.role
        session['password_session_version'] = self.prof.password_session_version
        session.save()
        page = self.client.get(reverse('quizzes:edit_questions', args=[q.quiz.pk]))
        self.assertContains(page, f'name="q_{q.pk}_regle"')
        self.assertContains(page, 'Règle du cours')
        format_attendu = self.client.get(reverse('quizzes:teacher_ai'))
        self.assertContains(format_attendu, '"explication": {')
        self.assertContains(format_attendu, '"regle":')
        self.assertContains(format_attendu, '"solution":')
        # Le JSON d'exemple affiché est lui-même importable.
        debut = format_attendu.content.decode()
        bloc = debut[debut.index('{\n  "quiz"'):]
        bloc = bloc[:bloc.index('</pre>')]
        exemple = json.loads(html_mod.unescape(bloc))
        self.assertIn('explication', exemple['quiz']['questions'][0])
