"""LaTeX (MathLive) → syntaxe de l'analyseur sûr (edubac_math.parser).

    \\frac{x+1}{2}            → ((x+1)/(2))
    \\sqrt[3]{x}               → root((x),(3))
    \\begin{pmatrix}1&2\\\\3&4\\end{pmatrix} → [[1,2],[3,4]]
    \\begin{cases}x+y=2\\\\x-y=0\\end{cases}  → x+y=2; x-y=0
Une commande inconnue est refusée (jamais exécutée).
"""
import re

from .parser import ParseError

SIMPLE = {
    'cdot': '*', 'times': '*', 'div': '/', 'pi': 'pi', 'infty': 'oo', 'le': '<=', 'leq': '<=',
    'ge': '>=', 'geq': '>=', 'ne': '!=', 'neq': '!=', 'lt': '<', 'gt': '>', 'lvert': '|', 'rvert': '|',
    'vert': '|', 'mid': '|', 'alpha': 'alpha', 'beta': 'beta', 'gamma': 'gamma', 'delta': 'delta',
    'theta': 'theta', 'lambda': 'lambda', 'mu': 'mu', 'omega': 'omega', 'varphi': 'varphi', 'phi': 'phi',
    'epsilon': 'epsilon', 'varepsilon': 'epsilon', 'rho': 'rho', 'sigma': 'sigma', 'tau': 'tau', 'psi': 'psi',
    'exponentialE': 'e', 'imaginaryI': 'i',
}
FUNCTIONS = {'sin', 'cos', 'tan', 'cot', 'arcsin', 'arccos', 'arctan', 'sinh', 'cosh', 'tanh',
             'exp', 'ln', 'log', 'sh', 'ch', 'th'}
IGNORED = {'left', 'right', 'displaystyle', 'textstyle', ',', ';', '!', ' ', 'quad', 'qquad', ':',
           'mathrm', 'mathit', 'operatorname', 'bigl', 'bigr', 'Bigl', 'Bigr', 'big', 'Big'}
TOKEN = re.compile(r'\\([A-Za-z]+|.)|([{}^_&])|(\\\\)|([^\\{}^_&]+)', re.S)


def _tokens(text):
    tokens = []
    for match in TOKEN.finditer(text.replace('\\\\', '\x00')):
        command, special, _, plain = match.groups()
        if command is not None:
            tokens.append(('cmd', command))
        elif special is not None:
            tokens.append(('sp', special))
        else:
            for part in re.split('(\x00)', plain):
                if part == '\x00':
                    tokens.append(('sp', 'newline'))
                elif part:
                    tokens.append(('txt', part))
    return tokens


class _Converter:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else (None, None)

    def group(self):
        """Argument : {…} ou un seul élément."""
        kind, val = self.peek()
        if (kind, val) == ('sp', '{'):
            self.pos += 1
            out = self.until('}')
            self.pos += 1
            return out
        if kind == 'txt':
            self.pos += 1
            text = val.lstrip()
            first, rest = (text[:1], text[1:]) if text else ('', '')
            if rest:
                self.tokens.insert(self.pos, ('txt', rest))
            return first
        if kind == 'cmd':
            self.pos += 1
            return self.command(val)
        raise ParseError('Argument manquant dans l’expression.')

    def until(self, closing):
        out = []
        while True:
            kind, val = self.peek()
            if kind is None:
                if closing is None:
                    return ''.join(out)
                raise ParseError('Accolade non fermée.')
            if closing is not None and kind == 'sp' and val == closing:
                return ''.join(out)
            if closing == 'end' and kind == 'cmd' and val == 'end':
                return ''.join(out)
            self.pos += 1
            if kind == 'txt':
                out.append(val)
            elif kind == 'cmd':
                out.append(self.command(val))
            elif val == '{':
                out.append('(' + self.until('}') + ')')
                self.pos += 1
            elif val == '^':
                out.append('^(' + self.group() + ')')
            elif val == '_':
                raise ParseError('Les indices (x₁…) ne sont pas pris en charge dans les calculs.')
            elif val == '&':
                out.append('\x01')
            elif val == 'newline':
                out.append('\x02')
            else:
                raise ParseError('Expression LaTeX invalide.')

    def command(self, name):
        if name in ('frac', 'dfrac', 'tfrac'):
            return f'(({self.group()})/({self.group()}))'
        if name == 'sqrt':
            index = None
            if self.peek() == ('txt', '[') or (self.peek()[0] == 'txt' and self.peek()[1].startswith('[')):
                kind, val = self.peek()
                end = val.find(']')
                if end < 0:
                    raise ParseError('Racine invalide.')
                index, rest = val[1:end], val[end + 1:]
                self.pos += 1
                if rest:
                    self.tokens.insert(self.pos, ('txt', rest))
            body = self.group()
            return f'root(({body}),({index}))' if index else f'sqrt({body})'
        if name == 'begin':
            env = self.group()
            body = self.until('end')
            self.pos += 1
            self.group()  # nom de l'environnement fermé
            rows = [row for row in body.split('\x02') if row.strip()]
            if env in ('pmatrix', 'bmatrix', 'matrix', 'vmatrix', 'Bmatrix'):
                return '[' + ','.join('[' + ','.join(c.strip() for c in row.split('\x01')) + ']' for row in rows) + ']'
            if env in ('cases', 'array', 'aligned', 'align', 'gathered'):
                return '; '.join(row.replace('\x01', '') for row in rows)
            raise ParseError(f'Environnement non pris en charge : {env}.')
        if name in SIMPLE:
            return f' {SIMPLE[name]} '
        if name in FUNCTIONS:
            return f' {name} '
        if name in IGNORED:
            if name in ('mathrm', 'mathit', 'operatorname'):
                return ' ' + self.group() + ' '
            return ' '
        if name in ('{', '}'):
            return '(' if name == '{' else ')'
        if name in ('lbrack', 'rbrack'):
            return '[' if name == 'lbrack' else ']'
        if name in ('%', '#', '$'):
            raise ParseError('Caractère non pris en charge.')
        raise ParseError(f'Commande LaTeX non prise en charge : \\{name}.')


def latex_to_text(latex):
    if not isinstance(latex, str) or not latex.strip():
        raise ParseError('Expression vide.')
    if len(latex) > 2000:
        raise ParseError('Expression trop longue.')
    text = latex.replace('{,}', ',').replace('\\placeholder{}', '')
    converter = _Converter(_tokens(text))
    out = converter.until(None)
    out = out.replace('\x01', ',').replace('\x02', ';')
    return re.sub(r'\s+', ' ', out).strip()
