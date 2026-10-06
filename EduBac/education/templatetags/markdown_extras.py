"""
Rendu Markdown + conservation des formules LaTeX pour KaTeX.
"""
import re
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
