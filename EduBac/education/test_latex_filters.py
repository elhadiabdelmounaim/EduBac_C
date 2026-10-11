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

    def test_course_boxes_classify_headings_and_preserve_math(self):
        source = (
            '## Chapitre\n\n### Définition\n\nUne fonction \\(f\\).\n\n'
            '### Propriété\n\n\\[f(x)=\\frac{1}{x}\\]\n\n'
            '### Exemple\n\nUn exemple.\n\n### Activité 1\n\nUne activité.\n\n'
            '### Application 2\n\nUne question.\n\n### Remarque\n\nUne remarque.\n'
        )
        rendered = self.render_filter(source, 'markdown_course_boxes')
        for kind in ('definition', 'property', 'example', 'activity', 'exercise', 'note'):
            self.assertIn(f'course-box--{kind}', rendered)
        self.assertEqual(rendered.count('<section '), 6)
        self.assertEqual(rendered.count('</section>'), 6)
        self.assertIn('$f$', rendered)
        self.assertIn(r'$$f(x)=\frac{1}{x}$$', rendered)
        self.assertNotIn('MATHBLOCK', rendered)
        self.assertNotIn('MATHINLINE', rendered)

    def test_course_boxes_stop_at_chapters_and_preserve_other_headings(self):
        rendered = self.render_filter(
            '### Définition\n\nTexte.\n\n## Chapitre suivant\n\n'
            '### Autre titre\n\nTexte libre.\n\n---\n\nFin.',
            'markdown_course_boxes',
        )
        self.assertIn('</section><h2>Chapitre suivant</h2>', rendered)
        self.assertIn('<h3>Autre titre</h3>', rendered)
        self.assertEqual(rendered.count('<section '), 1)
        self.assertIn('<hr>', rendered)

    def test_course_boxes_keep_math_html_escaped(self):
        rendered = self.render_filter(
            '### Exemple\n\n' + r'$\text{<script>alert(1)</script>}$',
            'markdown_course_boxes',
        )
        self.assertIn('&lt;script&gt;', rendered)
        self.assertNotIn('<script>', rendered)

    def test_course_boxes_support_adjacent_labeled_quotes(self):
        source = (
            '## Chapitre\n\n> **Activité 1**\n>\n> Calculer $f(x)$.\n\n'
            '> **Définition**\n>\n> Une fonction.\n\n'
            '> **Exemple**\n>\n> $$f(x)=x^2$$\n\n'
            '> **Exercice 2**\n>\n> 1. Calculer.\n\n---\n\nFin.'
        )
        rendered = self.render_filter(source, 'markdown_course_boxes')
        for kind in ('activity', 'definition', 'example', 'exercise'):
            self.assertIn(f'course-box--{kind}', rendered)
        self.assertEqual(rendered.count('<section '), 4)
        self.assertEqual(rendered.count('</section>'), 4)
        self.assertIn('<h3 class="course-box__title">Définition</h3>', rendered)
        self.assertIn('$f(x)$', rendered)
        self.assertIn('$$f(x)=x^2$$', rendered)
        self.assertNotIn('<blockquote>', rendered)
        self.assertIn('<hr>', rendered)

    def test_course_boxes_preserve_general_and_nested_quotes(self):
        source = '> Une citation.\n\n---\n\n> Citation extérieure.\n>\n> > **Définition**\n> >\n> > Citation intérieure.'
        self.assertEqual(
            self.render_filter(source, 'markdown_course_boxes'),
            self.render_filter(source, 'markdown_latex'),
        )

    def test_course_quote_boxes_escape_math(self):
        rendered = self.render_filter(
            '> **Exemple**\n>\n> ' + r'$\text{<script>alert(1)</script>}$',
            'markdown_course_boxes',
        )
        self.assertIn('course-box--example', rendered)
        self.assertIn('&lt;script&gt;', rendered)
        self.assertNotIn('<script>', rendered)
