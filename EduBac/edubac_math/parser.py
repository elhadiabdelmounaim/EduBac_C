"""Analyseur sûr : texte mathématique → expression SymPy, sans eval().

Accepte la notation de MathLive (ascii-math) et la saisie clavier habituelle :
    2x^2 - 3x + 1        sqrt(x+1)       (x+1)/(x-1)      sin(2x)
    e^(-x)               ln(x)/x         |x-2|            n!
    x^2 - 4 = 0          x + y = 2; x - y = 0    (système)
    x^2 - 1 > 0          [[1,2],[3,4]]   (matrice)        [1,2,3] (vecteur)
    π, ∞, √, ×, ÷, ≤, ≥, ², ³ …

Seuls les noms de la liste blanche sont reconnus ; un mot inconnu de plusieurs
lettres est lu comme un produit de variables (xy = x·y).
"""
import re

import sympy as sp

MAX_LENGTH = 600
MAX_DEPTH = 60

FUNCTIONS = {
    'sin': sp.sin, 'cos': sp.cos, 'tan': sp.tan, 'cot': sp.cot,
    'asin': sp.asin, 'acos': sp.acos, 'atan': sp.atan,
    'arcsin': sp.asin, 'arccos': sp.acos, 'arctan': sp.atan,
    'sinh': sp.sinh, 'cosh': sp.cosh, 'tanh': sp.tanh, 'sh': sp.sinh, 'ch': sp.cosh, 'th': sp.tanh,
    'exp': sp.exp, 'ln': sp.log, 'sqrt': sp.sqrt, 'abs': sp.Abs,
    'floor': sp.floor, 'ceil': sp.ceiling, 'sign': sp.sign, 'sgn': sp.sign,
    'E': sp.floor,  # partie entière, notation marocaine E(x)
}
CONSTANTS = {'pi': sp.pi, 'e': sp.E, 'oo': sp.oo, 'inf': sp.oo, 'infinity': sp.oo, 'i': sp.I}
GREEK = {'alpha', 'beta', 'gamma', 'delta', 'epsilon', 'theta', 'lambda', 'mu', 'omega', 'phi',
         'rho', 'sigma', 'tau', 'varphi', 'psi'}
RELATIONS = {'=': sp.Eq, '<': sp.Lt, '>': sp.Gt, '<=': sp.Le, '>=': sp.Ge, '!=': sp.Ne}
SUPERSCRIPTS = str.maketrans({'²': '^2', '³': '^3', '⁴': '^4'})
REPLACEMENTS = [
    ('π', 'pi'), ('∞', 'oo'), ('×', '*'), ('·', '*'), ('÷', '/'), ('−', '-'), ('≤', '<='),
    ('≥', '>='), ('≠', '!='), ('√', 'sqrt'), ('**', '^'), ('⁡', ''),
]
TOKEN_RE = re.compile(r'\s*(?:(\d+(?:\.\d+)?|\.\d+)|([A-Za-z]+)|(<=|>=|!=|[-+*/^()!,;=<>|\[\]]))')
# Mots connus reconnus dans une suite de lettres (« pix » → pi·x).
_KNOWN = sorted(set(CONSTANTS) | GREEK | {'pi'}, key=len, reverse=True)


class ParseError(ValueError):
    pass


def symbol(name):
    return sp.Symbol(name, real=name not in ('z',))


def _normalize(text):
    if not isinstance(text, str):
        raise ParseError('Expression manquante.')
    text = text.strip()
    if not text:
        raise ParseError('Expression vide.')
    if len(text) > MAX_LENGTH:
        raise ParseError('Expression trop longue.')
    for old, new in REPLACEMENTS:
        text = text.replace(old, new)
    return text.translate(SUPERSCRIPTS)


def tokenize(text):
    text = _normalize(text)
    tokens, pos = [], 0
    while pos < len(text):
        if text[pos].isspace():
            pos += 1
            continue
        match = TOKEN_RE.match(text, pos)
        if not match or match.end() == pos:
            raise ParseError(f'Caractère non reconnu : « {text[pos]} ».')
        number, word, op = match.groups()
        if number is not None:
            tokens.append(('num', number.replace(',', '.')))
        elif word is not None:
            tokens.append(('name', word))
        else:
            tokens.append(('op', op))
        pos = match.end()
    return _decimal_commas(tokens)


def _decimal_commas(tokens):
    """« 2,5 » = 2.5, sauf dans une matrice [..] ou un appel f(a, b) où la virgule sépare."""
    result, stack = [], []
    for index, token in enumerate(tokens):
        kind, val = token
        if val == '[':
            stack.append('list')
        elif val == '(':
            previous = result[-1] if result else None
            stack.append('call' if previous and previous[0] == 'name' else 'group')
        elif val in (')', ']') and stack:
            stack.pop()
        if (val == ',' and kind == 'op' and result and result[-1][0] == 'num' and '.' not in result[-1][1]
                and index + 1 < len(tokens) and tokens[index + 1][0] == 'num'
                and (not stack or stack[-1] == 'group')):
            continue  # virgule décimale : fusion avec le nombre suivant
        if kind == 'num' and len(result) >= 1 and index >= 1 and tokens[index - 1] == ('op', ',') \
                and result[-1][0] == 'num' and (not stack or stack[-1] == 'group') and '.' not in result[-1][1]:
            result[-1] = ('num', result[-1][1] + '.' + val)
            continue
        result.append(token)
    return result


class _Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0
        self.depth = 0

    def peek(self, offset=0):
        index = self.pos + offset
        return self.tokens[index] if index < len(self.tokens) else (None, None)

    def take(self, value=None):
        kind, val = self.peek()
        if kind is None or (value is not None and val != value):
            raise ParseError(f'« {value} » attendu.' if value else 'Expression incomplète.')
        self.pos += 1
        return kind, val

    def enter(self):
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise ParseError('Expression trop imbriquée.')

    # statement := expr (relop expr)?
    def statement(self):
        left = self.expr()
        kind, val = self.peek()
        if kind == 'op' and val in RELATIONS:
            self.take()
            right = self.expr()
            return RELATIONS[val](left, right)
        return left

    def expr(self):
        self.enter()
        value = self.term()
        while self.peek() in (('op', '+'), ('op', '-')):
            _, op = self.take()
            right = self.term()
            value = value + right if op == '+' else value - right
        self.depth -= 1
        return value

    def _starts_factor(self):
        kind, val = self.peek()
        return kind in ('num', 'name') or (kind == 'op' and val in ('(', '['))

    def term(self):
        value = self.unary()
        while True:
            kind, val = self.peek()
            if kind == 'op' and val in ('*', '/'):
                self.take()
                right = self.unary()
                value = value * right if val == '*' else value / right
            elif self._starts_factor():  # multiplication implicite : 2x, 3(x+1), x sin(x)
                value = value * self.power()
            else:
                return value

    def unary(self):
        kind, val = self.peek()
        if kind == 'op' and val in ('-', '+'):
            self.take()
            operand = self.unary()
            return -operand if val == '-' else operand
        return self.power()

    def power(self):
        base = self.postfix()
        if self.peek() == ('op', '^'):
            self.take()
            self.enter()
            exponent = self.unary()
            self.depth -= 1
            return sp.Pow(base, exponent)
        return base

    def postfix(self):
        value = self.primary()
        while self.peek() == ('op', '!'):
            self.take()
            value = sp.factorial(value)
        return value

    def arguments(self):
        self.take('(')
        args = [self.statement()]
        while self.peek() in (('op', ','), ('op', ';')):
            self.take()
            args.append(self.statement())
        self.take(')')
        return args

    def primary(self):
        kind, val = self.peek()
        if kind == 'num':
            self.take()
            return sp.Rational(val) if '.' in val else sp.Integer(val)
        if kind == 'op' and val == '(':
            self.take()
            self.enter()
            value = self.statement()
            self.depth -= 1
            self.take(')')
            return value
        if kind == 'op' and val == '|':
            self.take()
            value = self.expr()
            self.take('|')
            return sp.Abs(value)
        if kind == 'op' and val == '[':
            return self.matrix()
        if kind == 'name':
            self.take()
            return self.name(val)
        raise ParseError('Expression incomplète.' if kind is None else f'« {val} » inattendu.')

    def matrix(self):
        self.take('[')
        rows = []
        if self.peek() == ('op', '['):
            while True:
                self.take('[')
                row = [self.expr()]
                while self.peek() == ('op', ','):
                    self.take()
                    row.append(self.expr())
                self.take(']')
                rows.append(row)
                if self.peek() != ('op', ','):
                    break
                self.take()
            self.take(']')
            if len({len(r) for r in rows}) != 1:
                raise ParseError('Les lignes de la matrice n’ont pas la même longueur.')
            return sp.Matrix(rows)
        items = [self.expr()]
        while self.peek() == ('op', ','):
            self.take()
            items.append(self.expr())
        self.take(']')
        return sp.Matrix(items)  # vecteur colonne

    def name(self, word):
        followed_by_paren = self.peek() == ('op', '(')
        if word in FUNCTIONS and followed_by_paren:
            args = self.arguments()
            if word == 'sqrt' and len(args) == 2:
                return sp.root(args[0], args[1])
            if len(args) != 1:
                raise ParseError(f'{word} attend un seul argument.')
            return FUNCTIONS[word](args[0])
        if word == 'log' and followed_by_paren:
            args = self.arguments()  # log décimal au lycée marocain ; log(x, b) : base b
            if len(args) == 1:
                return sp.log(args[0], 10)
            if len(args) == 2:
                return sp.log(args[0], args[1])
            raise ParseError('log attend un ou deux arguments.')
        if word == 'root' and followed_by_paren:
            args = self.arguments()
            if len(args) != 2:
                raise ParseError('root(x, n) attend deux arguments.')
            return sp.root(args[0], args[1])
        if word in CONSTANTS:
            return CONSTANTS[word]
        if word in GREEK:
            return symbol(word)
        if word in FUNCTIONS or word == 'log':
            # Sans parenthèses (« sin x », « ln 2x ») : l'argument est le produit
            # qui suit, jusqu'au prochain opérateur ou à la prochaine fonction.
            if not self._starts_factor():
                raise ParseError(f'{word} doit être suivi de son argument : {word}(x).')
            argument = self.power()
            while self._starts_factor() and not (self.peek()[0] == 'name' and (
                    self.peek()[1] in FUNCTIONS or self.peek()[1] == 'log')):
                argument = argument * self.power()
            return sp.log(argument, 10) if word == 'log' else FUNCTIONS[word](argument)
        if len(word) == 1:
            return symbol(word)
        # Mot inconnu : produit de constantes connues et de variables à une lettre
        # (« xy » → x·y, « pix » → π·x).
        product, rest = sp.Integer(1), word
        while rest:
            known = next((k for k in _KNOWN if rest.startswith(k) and len(k) > 1), None)
            if known:
                product *= CONSTANTS.get(known) if known in CONSTANTS else symbol(known)
                rest = rest[len(known):]
                continue
            letter, rest = rest[0], rest[1:]
            product *= CONSTANTS[letter] if letter in ('e', 'i') else symbol(letter)
        return product


def parse(text):
    """Une expression, une équation / inéquation, ou une matrice."""
    parser = _Parser(tokenize(text))
    try:
        value = parser.statement()
    except RecursionError:
        raise ParseError('Expression trop imbriquée.') from None
    except (TypeError, ValueError, ZeroDivisionError) as exc:
        if isinstance(exc, ParseError):
            raise
        raise ParseError('Expression invalide.') from None
    if parser.pos != len(parser.tokens):
        raise ParseError(f'« {parser.tokens[parser.pos][1]} » inattendu.')
    return value


def parse_many(text):
    """Plusieurs expressions séparées par « ; » (système d'équations)."""
    if not isinstance(text, str):
        raise ParseError('Expression manquante.')
    parts = [part for part in text.split(';') if part.strip()]
    if not parts:
        raise ParseError('Expression vide.')
    if len(parts) > 10:
        raise ParseError('Dix équations au maximum.')
    return [parse(part) for part in parts]


def parse_symbol(text, default='x'):
    name = (text or default).strip()
    if not re.fullmatch(r'[A-Za-z]|' + '|'.join(sorted(GREEK)), name):
        raise ParseError('Variable invalide (une lettre, par exemple x).')
    return symbol(name)
