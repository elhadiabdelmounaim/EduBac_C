"""Présentation PowerPoint (professeurs seulement), guide de connexion imprimable, rapport de la
semaine, révision des erreurs, aide « mot de passe oublié » tolérante, e-mail absent."""
import io
import shutil
import tempfile
import zipfile
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from accounts.password_help import match_student
from classrooms.models import Classroom, ClassroomMember
from education.models import Course, Lesson
from notifications.models import Notification
from quizzes.models import Attempt, Choice, Question, Quiz, StudentAnswer

MEDIA = tempfile.mkdtemp(prefix='edubac-outils-')


@override_settings(MEDIA_ROOT=MEDIA, ALLOWED_HOSTS=['testserver'])
class OutilsDiversTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        media = tempfile.mkdtemp(dir=MEDIA)          # un dossier par test : rien ne passe d'un test à l'autre
        reglage = self.settings(MEDIA_ROOT=media)
        reglage.enable()
        self.addCleanup(reglage.disable)
        self.prof = User.objects.create_user(username='prof', email='prof@example.test', role='teacher')
        self.eleve = User.objects.create_user(username='amal.bennani', email='', role='student',
                                              first_name='Amal', last_name='Bennani')
        self.course = Course.objects.create(name='Mathématiques', niveau='1ere_bac_sc')
        self.lesson = Lesson.objects.create(course=self.course, title='Le produit scalaire dans le plan', order=4, content='')
        self.classe = Classroom.objects.create(name='1bac1', niveau='1ere_bac_sc', teacher=self.prof)
        ClassroomMember.objects.create(classroom=self.classe, user=self.eleve)

    def connecter(self, user):
        session = self.client.session
        session['user_id'] = user.pk
        session.save()

    # ---------- PowerPoint ----------
    def test_powerpoint_reserve_aux_professeurs(self):
        url = reverse('education:lesson_powerpoint', args=[self.lesson.pk])
        self.connecter(self.prof)
        page = self.client.get(reverse('education:lesson_detail', args=[self.lesson.pk]))
        self.assertContains(page, 'Aucune présentation pour cette leçon.')
        self.client.post(url, {'pptx': SimpleUploadedFile('diapos.pptx', b'PK pptx')})
        reponse = self.client.get(url)
        self.assertEqual(reponse.status_code, 200)
        self.assertIn('attachment', reponse['Content-Disposition'])
        self.assertEqual(b''.join(reponse.streaming_content), b'PK pptx')
        self.assertContains(self.client.get(reverse('education:lesson_detail', args=[self.lesson.pk])),
                            'Télécharger le PowerPoint')
        # Mauvais type refusé.
        self.client.post(url, {'pptx': SimpleUploadedFile('virus.exe', b'MZ')})
        self.assertEqual(b''.join(self.client.get(url).streaming_content), b'PK pptx')
        # Élève et visiteur : rien.
        self.connecter(self.eleve)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.cookies.clear()
        self.assertEqual(self.client.get(url).status_code, 404)
        # Retirer.
        self.connecter(self.prof)
        self.client.post(url, {'action': 'retirer'})
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_importer_powerpoint_depuis_le_zip(self):
        tampon = io.BytesIO()
        with zipfile.ZipFile(tampon, 'w') as z:
            z.writestr('EduBac_PowerPoint/1ere_Bac_Sciences/04_Le_produit_scalaire_dans_le_plan.pptx', b'PK diapos')
            z.writestr('EduBac_PowerPoint/1ere_Bac_Sciences/99_Lecon_inconnue.pptx', b'PK')
        chemin = tempfile.mktemp(suffix='.zip', dir=MEDIA)
        with open(chemin, 'wb') as f:
            f.write(tampon.getvalue())
        sortie = io.StringIO()
        call_command('importer_powerpoint', chemin, stdout=sortie)
        self.assertIn('1 présentation(s) rangée(s), 1 ignorée(s)', sortie.getvalue())
        from education.powerpoint import fichier
        self.assertEqual(fichier(self.lesson).read_bytes(), b'PK diapos')

    # ---------- Guide imprimable ----------
    def test_guide_eleves_avec_adresse_du_site(self):
        page = self.client.get(reverse('education:guide_eleves'))
        self.assertContains(page, 'http://testserver/')
        self.assertContains(page, 'Demande envoyée')
        self.assertContains(page, 'img/guide/inscription.png')
        self.assertContains(page, '3/3')
        self.assertContains(self.client.get(reverse('education:help')), reverse('education:guide_eleves'))

    # ---------- Rapport de la semaine ----------
    def test_rapport_de_la_semaine_page_et_commande(self):
        User.objects.filter(pk=self.eleve.pk).update(derniere_activite=timezone.now())
        quiz = Quiz.objects.create(title='Q', lesson=self.lesson, created_by=self.prof)
        Attempt.objects.create(quiz=quiz, student=self.eleve, score=80, submitted_at=timezone.now())
        self.connecter(self.prof)
        page = self.client.get(reverse('classrooms:rapport'))
        self.assertContains(page, '1bac1')
        self.assertContains(page, '80 %')
        sortie = io.StringIO()
        call_command('rapport_hebdo', stdout=sortie)
        self.assertIn('1 rapport(s) envoyé(s)', sortie.getvalue())
        n = Notification.objects.get(recipient=self.prof, type='rapport')
        self.assertIn('1bac1 : 1/1 élèves actifs', n.message)
        self.assertIn('moyenne 80 %', n.message)
        # « --si-dimanche » : rien les autres jours.
        if timezone.localdate().weekday() != 6:
            sortie = io.StringIO()
            call_command('rapport_hebdo', '--si-dimanche', stdout=sortie)
            self.assertIn('Pas dimanche', sortie.getvalue())
        self.connecter(self.eleve)
        self.assertNotEqual(self.client.get(reverse('classrooms:rapport')).status_code, 200)

    # ---------- Revoir mes erreurs ----------
    def test_revoir_mes_erreurs_seulement_les_dernieres_reponses_fausses(self):
        quiz = Quiz.objects.create(title='Produit scalaire', lesson=self.lesson, created_by=self.prof)
        q1 = Question.objects.create(quiz=quiz, order=1, text='Calculer u·v', regle='Expression analytique', explanation='u·v = 3')
        q2 = Question.objects.create(quiz=quiz, order=2, text='Question réussie ensuite')
        for q in (q1, q2):
            Choice.objects.create(question=q, text='3', is_correct=True)
            Choice.objects.create(question=q, text='5', is_correct=False)
        t1 = Attempt.objects.create(quiz=quiz, student=self.eleve, submitted_at=timezone.now() - timedelta(days=2))
        StudentAnswer.objects.create(attempt=t1, question=q1, answer='5', is_correct=False)
        StudentAnswer.objects.create(attempt=t1, question=q2, answer='5', is_correct=False)
        t2 = Attempt.objects.create(quiz=quiz, student=self.eleve, submitted_at=timezone.now())
        StudentAnswer.objects.create(attempt=t2, question=q2, answer='3', is_correct=True)
        self.connecter(self.eleve)
        page = self.client.get(reverse('quizzes:review_mistakes'))
        self.assertContains(page, 'Calculer u\\u00b7v')        # dans le JSON de la page
        self.assertNotContains(page, 'Question réussie ensuite')
        self.assertContains(page, 'Expression analytique')
        self.assertContains(page, '1 question que tu as ratée')
        autre = User.objects.create_user(username='autre', email='autre@example.test', role='student')
        self.connecter(autre)
        self.assertContains(self.client.get(reverse('quizzes:review_mistakes')), 'Aucune erreur à revoir')

    # ---------- Mot de passe oublié : nom approximatif ----------
    def test_correspondance_tolerante(self):
        self.assertEqual(match_student('Amal Bennani'), self.eleve)
        self.assertEqual(match_student('bennani  AMAL'), self.eleve)          # ordre, majuscules
        self.assertEqual(match_student('Amal Benani'), self.eleve)            # une lettre de travers
        self.assertEqual(match_student('Âmal Bennàni'), self.eleve)           # accents
        self.assertEqual(match_student('AMAL.BENNANI'), self.eleve)           # identifiant
        self.assertIsNone(match_student('Omar Alaoui'))
        self.assertIsNone(match_student('Amal'))                              # trop vague

    def test_homonymes_departages_par_la_classe(self):
        autre_classe = Classroom.objects.create(name='1bac2', niveau='1ere_bac_sc', teacher=self.prof)
        double = User.objects.create_user(username='amal2', email='a2@example.test', role='student',
                                          first_name='Amal', last_name='Bennani')
        ClassroomMember.objects.create(classroom=autre_classe, user=double)
        self.assertIsNone(match_student('Amal Bennani'))
        self.assertEqual(match_student('Amal Bennani', '1BAC 2'), double)

    # ---------- E-mail absent ----------
    def test_page_classe_sans_none(self):
        self.connecter(self.prof)
        page = self.client.get(reverse('classrooms:detail', args=[self.classe.pk]))
        self.assertContains(page, 'Identifiant : amal.bennani')
        self.assertNotContains(page, '>None<')
