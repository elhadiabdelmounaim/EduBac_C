"""Repère interactif, tableau de variations, arbre : stockage, droits et moteur JS."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from classrooms.models import Classroom

from .models import WhiteboardBoard


def plot(object_id='p1', items=None, **extra):
    return {'id': object_id, 'type': 'plot', 'x': 100, 'y': 100, 'w': 560, 'h': 420, 'title': 'Repère',
            'view': {'xmin': -6, 'xmax': 6, 'ymin': -4, 'ymax': 4}, 'opts': {'grid': True},
            'items': items if items is not None else [{'id': 'i1', 'line': 'f(x)=x^2-2', 'color': '#1d4fa3'},
                                                      {'id': 'i2', 'line': 'Placer(A;2;3)', 'color': '#d9480f'}],
            **extra}


@override_settings(ALLOWED_HOSTS=['testserver'])
class MathObjectsTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create(username='prof', email='prof@t.test', role='teacher')
        self.student = User.objects.create(username='omar', email='omar@t.test', first_name='Omar')
        self.classroom = Classroom.objects.create(name='2BAC', teacher=self.teacher, niveau='tronc_commun')
        self.classroom.add_member(self.student)
        self.board = WhiteboardBoard.objects.create(title='Fonctions', created_by=self.teacher, classroom=self.classroom,
                                                    content={'version': 1, 'objects': []})

    def sync(self, user, ops, since=0):
        session = self.client.session
        session['user_id'] = user.pk
        session.save()
        return self.client.post(reverse('whiteboard:sync', args=[self.board.pk]),
                                json.dumps({'since': since, 'client': f'c{user.pk}', 'ops': ops}),
                                content_type='application/json').json()

    def objects(self):
        self.board.refresh_from_db()
        return {o['id']: o for o in self.board.content['objects']}

    def test_teacher_places_plot_table_and_tree(self):
        data = self.sync(self.teacher, [
            {'op': 'add', 'object': plot()},
            {'op': 'add', 'object': {'id': 't1', 'type': 'vartable', 'x': 700, 'y': 100,
                                     'text': "x : -∞ ; 0 ; +∞\nf'(x) : - ; 0 ; +\nf : +∞ ; ↘ ; 0 ; ↗ ; +∞"}},
            {'op': 'add', 'object': {'id': 'a1', 'type': 'probtree', 'x': 100, 'y': 600, 'text': 'A : 0,3\nnon A : 0,7'}},
        ])
        self.assertEqual(data['rejected'], [])
        stored = self.objects()
        self.assertEqual(stored['p1']['items'][0]['line'], 'f(x)=x^2-2')
        self.assertEqual(set(stored), {'p1', 't1', 'a1'})

    def test_dragging_a_slider_is_an_ordinary_update(self):
        self.sync(self.teacher, [{'op': 'add', 'object': plot(items=[{'id': 'i1', 'line': 'a=Curseur(0;5;1)', 'val': 1}])}])
        moved = plot(items=[{'id': 'i1', 'line': 'a=Curseur(0;5;1)', 'val': 4}])
        data = self.sync(self.teacher, [{'op': 'update', 'object': moved}], since=1)
        self.assertEqual(data['rejected'], [])
        self.assertEqual(self.objects()['p1']['items'][0]['val'], 4)

    def test_invalid_plots_are_refused(self):
        too_many = plot(items=[{'id': f'i{n}', 'line': 'A=(1;1)'} for n in range(61)])
        no_size = plot('p2', w=0)
        long_line = plot('p3', items=[{'id': 'i1', 'line': 'x' * 601}])
        data = self.sync(self.teacher, [{'op': 'add', 'object': o} for o in (too_many, no_size, long_line)])
        self.assertEqual(len(data['rejected']), 3)
        self.assertEqual(self.objects(), {})

    def test_student_answers_the_exercise_but_cannot_change_the_plot(self):
        self.sync(self.teacher, [{'op': 'add', 'object': plot()}])
        WhiteboardBoard.objects.filter(pk=self.board.pk).update(students_can_edit=True)
        answer = {'id': 'ans1', 'type': 'plotanswer', 'plot': 'p1', 'target': 'A', 'mx': 2.1, 'my': 2.9,
                  'x': 500, 'y': 300, 'w': 12, 'h': 12}
        tampered = plot(items=[{'id': 'i1', 'line': 'Placer(A;0;0)'}])
        data = self.sync(self.student, [{'op': 'add', 'object': answer}, {'op': 'update', 'object': tampered}], since=1)
        self.assertEqual([r['id'] for r in data['rejected']], ['p1'])
        stored = self.objects()
        self.assertEqual(stored['ans1']['by'], self.student.pk)
        self.assertEqual(stored['p1']['items'][1]['line'], 'Placer(A;2;3)')

    def test_tutor_accepts_boards_with_math_objects(self):
        from .tutor_validation import validate_request
        payload = {'intent': 'explain', 'question': 'Que montre ce repère ?', 'objects': [
            {'id': 'p1', 'type': 'plot', 'x': 1, 'y': 1, 'w': 560, 'h': 420, 'text': 'Repère\nf(x)=x^2-2'},
            {'id': 't1', 'type': 'vartable', 'x': 1, 'y': 1, 'text': 'x : 0 ; 1'},
        ]}
        clean = validate_request(payload)
        self.assertEqual([o['type'] for o in clean['objects']], ['plot', 'vartable'])
        self.assertIn('f(x)=x^2-2', clean['objects'][0]['text'])


class MathEngineJavaScriptTests(SimpleTestCase):
    """Exécute les tests du moteur JS (node --test) quand Node.js est installé."""

    @unittest.skipUnless(shutil.which('node'), 'Node.js absent : tests JS non exécutés.')
    def test_engine(self):
        folder = Path(settings.BASE_DIR) / 'whiteboard' / 'js_tests'
        result = subprocess.run(['node', '--test', str(folder / 'math_engine.test.js')],
                                capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout[-3000:] + result.stderr[-2000:])
