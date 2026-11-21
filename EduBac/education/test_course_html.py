import tempfile
from pathlib import Path

from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Course, Lesson


@override_settings(ALLOWED_HOSTS=['testserver'])
class CourseHtmlTests(TestCase):
    """Cours en ligne (HTML) : « Ouvrir » affiche le cours, « Télécharger » garde le PDF."""

    def setUp(self):
        self.temp_media = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_media.cleanup)
        override = override_settings(MEDIA_ROOT=self.temp_media.name)
        override.enable()
        self.addCleanup(override.disable)
        self.course = Course.objects.create(name='Mathématiques', niveau='1ere_bac_sc')
        self.lesson = Lesson.objects.create(
            title='Le produit scalaire dans le plan', content='', course=self.course, order=4)
        self.other = Lesson.objects.create(
            title='Les suites numériques', content='', course=self.course, order=5)

    def add_pdf(self, lesson_folder, name='produit_scalaire.pdf'):
        folder = Path(self.temp_media.name) / 'lessons' / '1BAC_SE' / lesson_folder / 'Cours'
        folder.mkdir(parents=True)
        (folder / name).write_bytes(b'%PDF-1.4\nEduBac\n')
        return name

    def test_course_page_uses_local_static_files(self):
        response = self.client.get(reverse('education:lesson_course_html', args=[self.lesson.pk]))
        self.assertEqual(response.status_code, 200)
        page = response.content.decode()
        self.assertIn('/static/vendor/jquery/jquery-3.7.1.min.js', page)
        self.assertIn('/static/js/cours.js', page)
        self.assertIn('/static/vendor/mathjax/tex-svg-3.2.2.js', page)
        self.assertIn('/static/css/cours.css', page)
        self.assertNotIn('cdnjs', page)
        # Le LaTeX est transmis tel quel (pas interprété par Django).
        self.assertIn(r"\[\vu\cdot\vv=xx'+yy'", page)
        self.assertEqual(page.count('class="chap"'), 9)
        self.assertContains(response, reverse('education:lesson_detail', args=[self.lesson.pk]))

    def test_lesson_without_html_course_returns_404(self):
        response = self.client.get(reverse('education:lesson_course_html', args=[self.other.pk]))
        self.assertEqual(response.status_code, 404)

    def test_open_button_shows_html_and_download_keeps_pdf(self):
        name = self.add_pdf('04_le-produit-scalaire-dans-le-plan')
        html_url = reverse('education:lesson_course_html', args=[self.lesson.pk])
        pdf_url = reverse('education:lesson_document', args=[self.lesson.pk, 'Cours', name])
        page = self.client.get(reverse('education:lesson_detail', args=[self.lesson.pk])).content.decode()
        self.assertIn(f'href="{html_url}">Ouvrir</a>', page)
        self.assertIn(f'href="{pdf_url}?download=1"', page)
        self.assertNotIn(f'href="{pdf_url}">Ouvrir</a>', page)

    def test_lesson_without_html_course_keeps_pdf_open_button(self):
        name = self.add_pdf('05_les-suites-numeriques', 'suites.pdf')
        pdf_url = reverse('education:lesson_document', args=[self.other.pk, 'Cours', name])
        page = self.client.get(reverse('education:lesson_detail', args=[self.other.pk])).content.decode()
        self.assertIn(f'href="{pdf_url}">Ouvrir</a>', page)
        self.assertNotIn(reverse('education:lesson_course_html', args=[self.other.pk]), page)

    def test_html_course_is_offered_even_without_pdf(self):
        page = self.client.get(reverse('education:lesson_detail', args=[self.lesson.pk])).content.decode()
        self.assertIn('Cours en ligne', page)
        self.assertIn(reverse('education:lesson_course_html', args=[self.lesson.pk]), page)


@override_settings(ALLOWED_HOSTS=['testserver'])
class CourseBook3DTests(TestCase):
    """Livre 3D : données JSON du cours, Three.js servi localement, liens d'accès."""

    def setUp(self):
        course = Course.objects.create(name='Mathématiques', niveau='1ere_bac_sc')
        self.lesson = Lesson.objects.create(
            title='Le produit scalaire dans le plan', content='', course=course, order=4)
        self.other = Lesson.objects.create(title='Les suites numériques', content='', course=course, order=5)

    def test_book_page_embeds_lessons_and_local_three_js(self):
        response = self.client.get(reverse('education:lesson_book_3d', args=[self.lesson.pk]))
        self.assertEqual(response.status_code, 200)
        page = response.content.decode()
        self.assertIn('<script type="importmap">', page)
        self.assertIn('/static/vendor/three/three.module.min.js', page)
        self.assertIn('/static/vendor/three/addons/', page)
        self.assertIn('/static/js/livre3d.js', page)
        self.assertNotIn('cdnjs', page)
        data = response.context['livre']
        self.assertEqual(len(data['spreads']), 9)
        for spread in data['spreads']:
            self.assertIn(spread['predict']['answer'], range(len(spread['predict']['choices'])))
            self.assertGreaterEqual(len(spread['vocabulary']), 3)
            self.assertTrue(spread['flap'] and spread['concept'] and spread['formula'])
            self.assertTrue(spread['scene']['interactions'])
            actions = {step['action'] for step in spread['demo'] if step['action']}
            self.assertTrue(actions <= set(spread['scene']['interactions']), spread['id'])
        self.assertIn('id="livre-donnees"', page)

    def test_lesson_without_book_returns_404_and_has_no_link(self):
        self.assertEqual(self.client.get(reverse('education:lesson_book_3d', args=[self.other.pk])).status_code, 404)
        page = self.client.get(reverse('education:lesson_detail', args=[self.other.pk])).content.decode()
        self.assertNotIn('livre-3d', page)

    def test_book_is_linked_from_lesson_and_notebook(self):
        url = reverse('education:lesson_book_3d', args=[self.lesson.pk])
        self.assertContains(self.client.get(reverse('education:lesson_detail', args=[self.lesson.pk])), url)
        self.assertContains(self.client.get(reverse('education:lesson_course_html', args=[self.lesson.pk])), url)


class CoursePresentationAccessTests(TestCase):
    """Le mode « Présenter » n'est proposé qu'aux professeurs et aux administrateurs."""

    def setUp(self):
        course = Course.objects.create(name='Mathématiques', niveau='1ere_bac_sc')
        self.lesson = Lesson.objects.create(
            title='Le produit scalaire dans le plan', content='', course=course, order=4)
        self.url = reverse('education:lesson_course_html', args=[self.lesson.pk])

    def login_as(self, user):
        session = self.client.session
        session['user_id'] = user.pk
        session.save()

    def has_button(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        return 'id="coursPresenter"' in response.content.decode()

    def test_visitor_and_student_cannot_present(self):
        from django.contrib.auth import get_user_model
        self.assertFalse(self.has_button())
        student = get_user_model().objects.create_user(
            username='eleve', email='eleve@example.test', role='student')
        self.login_as(student)
        self.assertFalse(self.has_button())

    def test_teacher_and_admin_can_present(self):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        teacher = User.objects.create_user(username='prof', email='prof@example.test', role='teacher')
        self.login_as(teacher)
        self.assertTrue(self.has_button())
        admin = User.objects.create_user(username='admin', email='admin@example.test', role='student',
                                         is_staff=True, is_superuser=True)
        self.login_as(admin)
        self.assertTrue(self.has_button())
