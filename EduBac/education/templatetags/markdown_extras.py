"""
Rendu Markdown + conservation des formules LaTeX pour KaTeX.
"""
import re
import unicodedata
from html import unescape
from django import template
from django.utils.safestring import mark_safe
from django.utils.html import escape

register = template.Library()

_MATH_BLOCK = re.compile(
    r'\$\$(.+?)\$\$|\\\[(.+?)\\\]',
    re.DOTALL,
)
_MATH_INLINE = re.compile(
    r'(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)|\\\((.+?)\\\)',
    re.DOTALL,
)


def _protect_math(text: str):
    blocks = []
    inlines = []

    def save_block(m):
        blocks.append(m.group(0))
        return f'@@MATHBLOCK{len(blocks)-1}@@'

    def save_inline(m):
        inlines.append(m.group(0))
        return f'@@MATHINLINE{len(inlines)-1}@@'

    text = _MATH_BLOCK.sub(save_block, text)
    text = _MATH_INLINE.sub(save_inline, text)
    return text, blocks, inlines


def _normalize_delimiters(formula: str) -> str:
    s = formula.strip()
    if s.startswith('\\[') and s.endswith('\\]'):
        return '$$' + s[2:-2] + '$$'
    if s.startswith('\\(') and s.endswith('\\)'):
        return '$' + s[2:-2] + '$'
    return formula


def _escape_math_formula(formula: str) -> str:
    """Escape HTML in formula bodies before returning the surrounding HTML safe."""
    formula = _normalize_delimiters(formula)
    if formula.startswith('$$') and formula.endswith('$$'):
        return '$$' + str(escape(formula[2:-2])) + '$$'
    if formula.startswith('$') and formula.endswith('$'):
        return '$' + str(escape(formula[1:-1])) + '$'
    return str(escape(formula))


def _restore_math(html: str, blocks, inlines) -> str:
    for i, b in enumerate(blocks):
        token = f'@@MATHBLOCK{i}@@'
        formula = _escape_math_formula(b)
        paragraph = f'<p>{token}</p>'
        if paragraph in html:
            html = html.replace(
                paragraph,
                f'<div class="math-block">{formula}</div>',
            )
        else:
            html = html.replace(token, formula)
    for i, s in enumerate(inlines):
        html = html.replace(
            f'@@MATHINLINE{i}@@',
            _escape_math_formula(s),
        )
    return html


def _render_markdown(text: str) -> str:
    if not text:
        return ''
    try:
        import markdown as md
        return md.markdown(
            text,
            extensions=[
                'extra',
                'sane_lists',
                'nl2br',
                'tables',
                'fenced_code',
            ],
            output_format='html5',
        )
    except Exception:
        return '<p>' + escape(text).replace('\n', '<br>') + '</p>'


@register.filter(name='markdown_latex')
def markdown_latex(value):
    if not value:
        return ''
    raw = str(value)
    protected, blocks, inlines = _protect_math(raw)
    html = _render_markdown(protected)
    html = _restore_math(html, blocks, inlines)
    return mark_safe(html)


def _course_box_kind(heading):
    text = unescape(re.sub(r'<[^>]+>', '', heading)).strip().casefold()
    text = ''.join(
        char for char in unicodedata.normalize('NFKD', text)
        if not unicodedata.combining(char)
    )
    groups = (
        ('definition', ('definition', 'fonction periodique', 'fonction composee', 'extremum')),
        ('property', ('propriete', 'sens de variation', 'technique')),
        ('example', ('exemple',)),
        ('exercise', ('application', 'exercice')),
        ('activity', ('activite',)),
        ('note', ('remarque', 'interpretation graphique')),
    )
    return next(
        (kind for kind, prefixes in groups if text.startswith(prefixes)),
        None,
    )


def _decorate_course_quotes(html):
    """Support pedagogical labels inside quotes, including adjacent quotes."""
    def decorate(match):
        body = match.group(1)
        # Keep nested/general quotations untouched.
        if '<blockquote' in body:
            return match.group(0)
        labels = list(re.finditer(
            r'<p>\s*<strong>(.*?)</strong>\s*</p>', body, re.DOTALL,
        ))
        labels = [(label, _course_box_kind(label.group(1))) for label in labels]
        labels = [(label, kind) for label, kind in labels if kind]
        if not labels:
            return match.group(0)
        output = []
        prefix = body[:labels[0][0].start()]
        if prefix.strip():
            output.append(f'<blockquote>{prefix}</blockquote>')
        for index, (label, kind) in enumerate(labels):
            end = labels[index + 1][0].start() if index + 1 < len(labels) else len(body)
            output.append(
                f'<section class="course-box course-box--{kind}">'
                f'<h3 class="course-box__title">{label.group(1)}</h3>'
                f'<div class="course-box__body">{body[label.end():end]}</div>'
                '</section>'
            )
        return ''.join(output)

    return re.sub(r'<blockquote>(.*?)</blockquote>', decorate, html, flags=re.DOTALL)


@register.filter(name='markdown_course_boxes')
def markdown_course_boxes(value):
    """Decorate pedagogical headings, keeping the original Markdown and math."""
    html = str(markdown_latex(value))
    parts = re.split(
        r'(<h[1-3]\b[^>]*>.*?</h[1-3]>|<hr\b[^>]*>)',
        html, flags=re.DOTALL,
    )
    output, opened = [], False
    for part in parts:
        boundary = re.match(r'<(?:h[1-3]|hr)\b', part)
        if boundary and opened:
            output.append('</div></section>')
            opened = False
        kind = _course_box_kind(part) if re.match(r'<h3\b', part) else None
        if kind:
            # Markdown emits plain h3 tags; keep their text and LaTeX unchanged.
            title = re.sub(r'^<h3>', '<h3 class="course-box__title">', part)
            output.extend((
                f'<section class="course-box course-box--{kind}">',
                title, '<div class="course-box__body">',
            ))
            opened = True
        else:
            output.append(part)
    if opened:
        output.append('</div></section>')
    return mark_safe(_decorate_course_quotes(''.join(output)))


@register.filter(name='latex')
def latex_only(value):
    """Texte + formules LaTeX (sans Markdown). Pour questions / reponses."""
    if not value:
        return ''
    raw = str(value).strip()
    protected, blocks, inlines = _protect_math(raw)
    parts = re.split(r'(@@MATH(?:BLOCK|INLINE)\d+@@)', protected)
    out = []
    for part in parts:
        if part.startswith('@@MATH'):
            out.append(part)
        else:
            out.append(escape(part).replace('\n', '<br>'))
    html = ''.join(out)
    html = _restore_math(html, blocks, inlines)
    return mark_safe(html)


@register.filter(name='markdown_plain')
def markdown_plain(value):
    if not value:
        return ''
    text = str(value)
    text = re.sub(r'#+\s*', '', text)
    text = re.sub(r'[*_`]', '', text)
    return text
