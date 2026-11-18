from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User


@override_settings(ALLOWED_HOSTS=['testserver'])
class InfoPagesTests(TestCase):
    PAGES = ['help', 'bac', 'contact', 'legal', 'privacy', 'terms']

    def test_public_pages_render_with_description_and_footer_links(self):
        for name in self.PAGES:
            with self.subTest(page=name):
                response = self.client.get(reverse(f'education:{name}'))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, '<meta name="description"')
                self.assertContains(response, 'property="og:title"')
                self.assertContains(response, f'href="{reverse("education:privacy")}"')

    def test_missing_identity_is_flagged_for_the_teacher_only(self):
        with self.settings():
            from config import site_info
            original = dict(site_info.SITE_INFO)
            site_info.SITE_INFO.update(publisher_name='', contact_email='', city='')
            try:
                page = self.client.get(reverse('education:legal'))
                self.assertContains(page, 'à compléter')
                self.assertNotContains(page, 'Visible par l’administrateur')
                teacher = User.objects.create(username='prof', role='teacher')
                session = self.client.session
                session['user_id'] = teacher.pk
                session.save()
                self.assertContains(self.client.get(reverse('education:legal')), 'Visible par l’administrateur')
                site_info.SITE_INFO.update(publisher_name='Prof Test', contact_email='prof@example.test', city='Rabat')
                page = self.client.get(reverse('education:legal'))
                self.assertContains(page, 'Prof Test')
                self.assertContains(page, 'mailto:prof@example.test')
                self.assertNotContains(page, 'Visible par l’administrateur')
            finally:
                site_info.SITE_INFO.clear()
                site_info.SITE_INFO.update(original)

    def test_robots_and_sitemap_expose_only_public_pages(self):
        robots = self.client.get('/robots.txt').content.decode()
        self.assertIn('Disallow: /chat/', robots)
        self.assertIn('Sitemap: http://testserver/sitemap.xml', robots)
        sitemap = self.client.get('/sitemap.xml').content.decode()
        self.assertIn('<loc>http://testserver/aide/</loc>', sitemap)
        self.assertIn('<loc>http://testserver/niveaux/</loc>', sitemap)
        self.assertNotIn('/chat/', sitemap)
        self.assertNotIn('/compte/connexion', sitemap)

    def test_signup_links_to_terms_and_privacy(self):
        page = self.client.get(reverse('accounts:register_student'))
        self.assertContains(page, reverse('education:terms'))
        self.assertContains(page, reverse('education:privacy'))
