from django.template import Context, Template
from django.test import SimpleTestCase


class LatexTemplateFilterTests(SimpleTestCase):
    @staticmethod
    def render_filter(value, filter_name='latex'):
        template = Template(
            '{% load markdown_extras %}{{ value|' + filter_name + ' }}'
        )
        return template.render(Context({'value': value}))

    def test_formula_bodies_escape_html_metacharacters(self):
        rendered = self.render_filter(r'$x<3$ and $a<b$')

        self.assertIn('$x&lt;3$', rendered)
        self.assertIn('$a&lt;b$', rendered)

    def test_html_tags_inside_and_outside_math_are_not_restored_as_markup(self):
        rendered = self.render_filter(
            r'$\text{<b>gras</b>}$ and <b>plain</b>'
        )

        self.assertIn('&lt;b&gt;gras&lt;/b&gt;', rendered)
        self.assertIn('&lt;b&gt;plain&lt;/b&gt;', rendered)
        self.assertNotIn('<b>', rendered)

    def test_script_markup_inside_math_is_escaped(self):
        rendered = self.render_filter(
            r'$\text{<script>alert(1)</script>}$',
            filter_name='markdown_latex',
        )

        self.assertIn('&lt;script&gt;', rendered)
        self.assertNotIn('<script>', rendered)
