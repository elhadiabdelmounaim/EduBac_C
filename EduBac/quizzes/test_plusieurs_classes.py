"""Envoyer un quiz à plusieurs classes du même niveau : à l'import, depuis le brouillon et depuis
la page « Affecter ». Tout ou rien : une classe refusée et aucun élève ne reçoit le quiz."""
import json
import uuid

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from classrooms.models import Classroom, ClassroomMember
from notifications.models import Notification

from .models import Quiz, QuizAssignment
from .test_json_import import QuizJsonImportTests


@override_settings(ALLOWED_HOSTS=['testserver'])
class QuizPlusieursClassesTests(TestCase):
    """self.classroom (TC A : self.student) et self.other_class (TC B : self.outsider), même niveau.
    Mêmes données que les tests d'import (sans rejouer leurs tests)."""
    login = QuizJsonImportTests.login

    def setUp(self):
        QuizJsonImportTests.setUp(self)
        # Un élève inscrit dans les deux classes ne reçoit le quiz qu'une fois.
        self.double = User.objects.create_user(username='double', email='double@example.test', role='student')
        ClassroomMember.objects.create(classroom=self.classroom, user=self.double)
        ClassroomMember.objects.create(classroom=self.other_class, user=self.double)

    def importer(self, *classes, send_now=False):
        content = json.dumps(self.document, ensure_ascii=False).encode('utf-8')
        data = {
            'action': 'import_json', 'niveau': self.lesson.course.niveau, 'course': self.lesson.course_id,
            'lesson': self.lesson.pk, 'seconds_per_question': 20, 'generation_id': str(uuid.uuid4()),
            'target_classroom': [c.pk for c in classes],
            'quiz_json': SimpleUploadedFile('quiz.json', content, content_type='application/json'),
        }
        if send_now:
            data['send_now'] = '1'
        return self.client.post(self.url, data)

    def destinataires(self, quiz):
        return set(QuizAssignment.objects.filter(quiz=quiz).values_list('student__username', flat=True))

    def test_import_et_envoi_a_deux_classes(self):
        response = self.importer(self.classroom, self.other_class, send_now=True)
        self.assertRedirects(response, reverse('quizzes:manage'), fetch_redirect_response=False)
        quiz = Quiz.objects.get()
        self.assertEqual(quiz.status, 'published')
        self.assertEqual(self.destinataires(quiz), {'json-student', 'json-outsider', 'double'})
        self.assertEqual(Notification.objects.filter(recipient=self.double, type='quiz_assigned').count(), 1)
        page = self.client.get(reverse('quizzes:manage'))
        self.assertContains(page, 'envoyé aux classes TC A et TC B')

    def test_brouillon_garde_les_deux_classes_cochees(self):
        response = self.importer(self.classroom, self.other_class)
        quiz = Quiz.objects.get()
        self.assertEqual(quiz.status, 'draft')
        self.assertEqual(quiz.classroom, self.classroom)
        self.assertFalse(QuizAssignment.objects.exists())
        self.assertIn(f'classes={self.classroom.pk},{self.other_class.pk}', response['Location'])
        page = self.client.get(response['Location']).content.decode()
        for classe in (self.classroom, self.other_class):
            self.assertRegex(page, rf'name="classroom" value="{classe.pk}"\s+checked')

    def test_envoi_du_brouillon_a_deux_classes_puis_recapitulatif(self):
        self.importer(self.classroom)
        quiz = Quiz.objects.get()
        response = self.client.post(self.url, {
            'action': 'send', 'quiz_id': quiz.pk, 'classroom': [self.classroom.pk, self.other_class.pk],
        })
        self.assertRedirects(response, reverse('quizzes:manage'), fetch_redirect_response=False)
        self.assertEqual(self.destinataires(quiz), {'json-student', 'json-outsider', 'double'})
        page = self.client.get(f'{self.url}?quiz={quiz.pk}')
        self.assertContains(page, 'Déjà affecté à TC A, TC B (3 élèves)')
        self.assertContains(page, 'Déjà reçu')

    def test_renvoyer_plus_tard_a_une_autre_classe(self):
        self.importer(self.classroom, send_now=True)
        quiz = Quiz.objects.get()
        self.assertEqual(self.destinataires(quiz), {'json-student', 'double'})
        self.client.post(self.url, {'action': 'send', 'quiz_id': quiz.pk, 'classroom': [self.other_class.pk]})
        self.assertEqual(self.destinataires(quiz), {'json-student', 'json-outsider', 'double'})
        self.assertEqual(Notification.objects.filter(recipient=self.double, type='quiz_assigned').count(), 1)

    def test_tout_ou_rien_classe_sans_eleve_ou_autre_niveau(self):
        vide = Classroom.objects.create(name='TC vide', niveau='tronc_commun', teacher=self.teacher)
        self.importer(self.classroom)
        quiz = Quiz.objects.get()
        response = self.client.post(self.url, {'action': 'send', 'quiz_id': quiz.pk,
                                               'classroom': [self.classroom.pk, vide.pk]})
        self.assertFalse(QuizAssignment.objects.exists())
        page = self.client.get(response['Location'])
        self.assertContains(page, 'La classe « TC vide » ne contient aucun élève.')
        autre_niveau = Classroom.objects.create(name='SM', niveau='1ere_bac_sm', teacher=self.teacher)
        ClassroomMember.objects.create(classroom=autre_niveau, user=self.outsider)
        self.client.post(self.url, {'action': 'send', 'quiz_id': quiz.pk,
                                    'classroom': [self.classroom.pk, autre_niveau.pk]})
        self.assertFalse(QuizAssignment.objects.exists())
        quiz.refresh_from_db()
        self.assertEqual(quiz.status, 'draft')

    def test_classe_d_un_autre_professeur_refusee(self):
        autre = User.objects.create_user(username='autre-prof2', email='ap2@example.test', role='teacher')
        etrangere = Classroom.objects.create(name='Étrangère', niveau='tronc_commun', teacher=autre)
        ClassroomMember.objects.create(classroom=etrangere, user=self.outsider)
        self.importer(self.classroom)
        quiz = Quiz.objects.get()
        response = self.client.post(self.url, {'action': 'send', 'quiz_id': quiz.pk,
                                               'classroom': [self.classroom.pk, etrangere.pk]})
        self.assertEqual(response.status_code, 404)
        self.assertFalse(QuizAssignment.objects.exists())
        # À l'import aussi : rien n'est créé.
        Quiz.objects.all().delete()
        self.importer(self.classroom, etrangere, send_now=True)
        self.assertFalse(Quiz.objects.exists())

    def test_page_affecter_plusieurs_classes(self):
        self.importer(self.classroom)
        quiz = Quiz.objects.get()
        page = self.client.get(reverse('quizzes:assign'))
        self.assertContains(page, f'type="checkbox" name="classroom" value="{self.other_class.pk}"')
        self.client.post(reverse('quizzes:assign'), {
            'quiz': quiz.pk, 'target': 'classroom', 'classroom': [self.classroom.pk, self.other_class.pk],
        })
        self.assertEqual(self.destinataires(quiz), {'json-student', 'json-outsider', 'double'})

    def test_une_seule_classe_comme_avant(self):
        self.importer(self.classroom, send_now=True)
        quiz = Quiz.objects.get()
        self.assertEqual(quiz.classroom, self.classroom)
        self.assertEqual(self.destinataires(quiz), {'json-student', 'double'})
