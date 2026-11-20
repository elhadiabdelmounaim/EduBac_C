"""Calculs symboliques (SymPy) avec limites de temps et de mémoire.

compute(action, expression, **options) → {"ok": True, "latex": ..., "text": ..., ...}
                                        ou {"ok": False, "error": "message en français"}

Chaque calcul s'exécute dans un processus séparé (temps et mémoire limités) :
une expression piège (9^9^9, intégrale interminable…) ne bloque jamais le serveur.
"""
import multiprocessing
import os

import sympy as sp

from .parser import ParseError, parse, parse_many, parse_symbol

TIMEOUT_SECONDS = 8
MEMORY_LIMIT = 512 * 1024 * 1024
ACTIONS = (
    'simplify', 'expand', 'factor', 'evaluate', 'derivative', 'integral', 'limit',
    'solve', 'determinant', 'inverse', 'transpose', 'equal', 'asymptotes', 'variations',
)
ACTION_LABELS = {
    'simplify': 'Simplifier', 'expand': 'Développer', 'factor': 'Factoriser',
    'evaluate': 'Valeur approchée', 'derivative': 'Dériver', 'integral': 'Intégrer',
    'limit': 'Limite', 'solve': 'Résoudre', 'determinant': 'Déterminant',
    'inverse': 'Inverse', 'transpose': 'Transposée', 'equal': 'Comparer',
    'asymptotes': 'Asymptotes', 'variations': 'Tableau de variations',
}


class MathError(ValueError):
    pass


def latex(value):
    return sp.latex(value, ln_notation=True, imaginary_unit='i', decimal_separator='comma') \
        if not isinstance(value, str) else value


def _expr(value):
    if isinstance(value, sp.MatrixBase) or isinstance(value, sp.core.relational.Relational):
        raise MathError('Une expression simple est attendue ici.')
    return value


def _matrix(value):
    if not isinstance(value, sp.MatrixBase):
        raise MathError('Une matrice est attendue, par exemple [[1,2],[3,4]].')
    return value


def _point(text):
    text = (text or '').strip()
    if text in ('+oo', 'oo', '+inf', 'inf', '+∞', '∞'):
        return sp.oo
    if text in ('-oo', '-inf', '-∞'):
        return -sp.oo
    return _expr(parse(text))


def _solve(text, variable):
    items = parse_many(text)
    if len(items) == 1:
        item = items[0]
        if isinstance(item, sp.core.relational.Relational) and not isinstance(item, (sp.Eq, sp.Ne)):
            solution = sp.solveset(item, variable, sp.S.Reals)  # inéquation → intervalle(s)
        else:
            equation = item if isinstance(item, sp.Eq) else sp.Eq(item, 0)
            domain = sp.S.Complexes if equation.has(sp.I) else sp.S.Reals
            solution = sp.solveset(equation, variable, domain)
        return {'latex': f'S = {latex(solution)}', 'text': str(solution)}
    equations = [item if isinstance(item, sp.Eq) else sp.Eq(item, 0) for item in items]
    unknowns = sorted(set().union(*(eq.free_symbols for eq in equations)), key=lambda s: s.name)
    solutions = sp.solve(equations, unknowns, dict=True)
    if not solutions:
        return {'latex': r'S = \varnothing', 'text': 'aucune solution'}
    parts = [r'\left(' + ', '.join(latex(sol.get(u, u)) for u in unknowns) + r'\right)' for sol in solutions]
    head = r'\left(' + ', '.join(latex(u) for u in unknowns) + r'\right)'
    return {'latex': f'{head} \\in \\left\\{{{", ".join(parts)}\\right\\}}', 'text': str(solutions)}


def _domain(f, x):
    try:
        return sp.calculus.util.continuous_domain(f, x, sp.S.Reals)
    except (NotImplementedError, TypeError, ValueError):
        return sp.S.Reals


def _boundaries(domain):
    points = set()
    for part in (domain.args if isinstance(domain, sp.Union) else (domain,)):
        if isinstance(part, sp.Interval):
            points.update(p for p in (part.start, part.end) if p.is_finite)
        elif isinstance(part, sp.FiniteSet):
            points.update(part)
    return sorted(points, key=lambda v: float(v))


def asymptotes(f, x):
    f = _expr(f)
    result = {'vertical': [], 'horizontal': [], 'oblique': []}
    domain = _domain(f, x)
    for a in _boundaries(domain):
        for direction in ('-', '+'):
            try:
                value = sp.limit(f, x, a, direction)
            except (NotImplementedError, ValueError):
                continue
            if value in (sp.oo, -sp.oo) and a not in result['vertical']:
                result['vertical'].append(a)
    for side, infinity in (('+', sp.oo), ('-', -sp.oo)):
        try:
            value = sp.limit(f, x, infinity)
        except (NotImplementedError, ValueError):
            continue
        if value.is_finite and value.is_real:
            result['horizontal'].append({'side': side, 'value': value})
        elif value in (sp.oo, -sp.oo):
            try:
                slope = sp.limit(f / x, x, infinity)
                if slope.is_finite and slope != 0:
                    intercept = sp.limit(f - slope * x, x, infinity)
                    if intercept.is_finite:
                        result['oblique'].append({'side': side, 'slope': slope, 'intercept': intercept})
            except (NotImplementedError, ValueError):
                pass
    lines = [f'x = {latex(a)}' for a in result['vertical']]
    seen = set()
    for h in result['horizontal']:
        line = f"y = {latex(h['value'])}"
        if line not in seen:
            seen.add(line)
            lines.append(line + (r' \text{ en } ' + ('+' if h['side'] == '+' else '-') + r'\infty'))
    for o in result['oblique']:
        line = f"y = {latex(o['slope'] * x + o['intercept'])}"
        if line not in seen:
            seen.add(line)
            lines.append(line + (r' \text{ en } ' + ('+' if o['side'] == '+' else '-') + r'\infty'))
    text_latex = r'\text{Aucune asymptote}' if not lines else r'\begin{aligned}' + r'\\'.join(lines) + r'\end{aligned}'
    return {
        'latex': text_latex,
        'text': '; '.join(lines) or 'aucune',
        'vertical': [str(a) for a in result['vertical']],
        'horizontal': [{'side': h['side'], 'value': float(h['value'])} for h in result['horizontal']],
        'oblique': [{'side': o['side'], 'slope': float(o['slope']), 'intercept': float(o['intercept'])}
                    for o in result['oblique']],
    }


def variations(f, x, name='f'):
    """Tableau de variations : points clés, signe de f', valeurs et limites de f."""
    f = _expr(f)
    domain = _domain(f, x)
    if domain == sp.S.EmptySet:
        raise MathError('Fonction définie nulle part.')
    derivative = sp.simplify(sp.diff(f, x))
    critical = sp.solveset(sp.Eq(derivative, 0), x, domain)
    if not isinstance(critical, sp.FiniteSet):
        critical = sp.FiniteSet(*[c for c in getattr(critical, 'args', ()) if getattr(c, 'is_number', False)]) \
            if isinstance(critical, sp.Union) else sp.S.EmptySet
    lower = domain.inf if domain.inf.is_finite else -sp.oo
    upper = domain.sup if domain.sup.is_finite else sp.oo
    inner = sorted({p for p in list(critical) + _boundaries(domain) if p.is_real and lower < p < upper},
                   key=lambda v: float(v))
    if len(inner) > 12:
        raise MathError('Trop de points particuliers pour un tableau lisible.')
    points = [lower] + inner + [upper]
    forbidden = {p for p in inner if p not in domain}

    def value_at(point, direction=None):
        try:
            if point in (sp.oo, -sp.oo):
                return sp.limit(f, x, point)
            if point in forbidden or point not in domain:
                return sp.limit(f, x, point, direction)
            return sp.simplify(f.subs(x, point))
        except (NotImplementedError, ValueError):
            return sp.nan

    signs, arrows = [], []
    for a, b in zip(points, points[1:]):
        if a.is_infinite and b.is_infinite:
            probe = sp.Integer(0)
        elif a.is_infinite:
            probe = b - 1
        elif b.is_infinite:
            probe = a + 1
        else:
            probe = (a + b) / 2
        if probe not in domain:
            signs.append('||')
            arrows.append('')
            continue
        sign = sp.sign(sp.N(derivative.subs(x, probe)))
        signs.append('+' if sign > 0 else '-' if sign < 0 else '0')
        arrows.append('up' if sign > 0 else 'down' if sign < 0 else 'flat')
    values = []
    for index, point in enumerate(points):
        if point in forbidden:
            values.append({'left': latex(value_at(point, '-')), 'right': latex(value_at(point, '+')),
                           'forbidden': True})
        else:
            direction = '+' if index == 0 else '-'
            values.append({'value': latex(value_at(point, direction))})
    return {
        'latex': f"{name}'(x) = {latex(derivative)}",
        'text': str(derivative),
        'table': {
            'variable': str(x), 'function': name, 'derivative': latex(derivative),
            'points': [latex(p) for p in points], 'signs': signs, 'arrows': arrows, 'values': values,
            'forbidden': [latex(p) for p in sorted(forbidden, key=lambda v: float(v))],
        },
    }


def _run(action, expression, options):
    if action not in ACTIONS:
        raise MathError('Opération inconnue.')
    x = parse_symbol(options.get('variable'))
    if action == 'solve':
        return _solve(expression, x)
    if action == 'equal':
        a = _expr(parse(expression))
        b = _expr(parse(options.get('other', '')))
        same = sp.simplify(a - b) == 0
        if not same:
            try:
                same = bool(sp.Abs(sp.N(a - b)) < 1e-12) if (a - b).is_number else False
            except TypeError:
                same = False
        return {'latex': r'\text{Égales}' if same else r'\text{Différentes}', 'text': str(same), 'equal': same}
    value = parse(expression)
    if action in ('determinant', 'inverse', 'transpose'):
        matrix = _matrix(value)
        if action == 'determinant':
            result = matrix.det()
        elif action == 'transpose':
            result = matrix.T
        else:
            if matrix.det() == 0:
                raise MathError('Matrice non inversible (déterminant nul).')
            result = matrix.inv()
        return {'latex': latex(sp.simplify(result)), 'text': str(result)}
    if action == 'asymptotes':
        return asymptotes(value, x)
    if action == 'variations':
        return variations(value, x, (options.get('name') or 'f')[:3])
    if isinstance(value, sp.core.relational.Relational):
        raise MathError('Utilisez « Résoudre » pour une équation ou une inéquation.')
    if action == 'simplify':
        result = value.applyfunc(sp.simplify) if isinstance(value, sp.MatrixBase) else sp.simplify(value)
    elif action == 'expand':
        result = sp.expand(value)
    elif action == 'factor':
        result = sp.factor(value)
    elif action == 'evaluate':
        result = sp.N(value, 12)
    elif action == 'derivative':
        order = int(options.get('order') or 1)
        if not 1 <= order <= 5:
            raise MathError('Ordre de dérivation entre 1 et 5.')
        result = sp.simplify(sp.diff(_expr(value), x, order))
    elif action == 'integral':
        lower, upper = options.get('lower'), options.get('upper')
        if lower not in (None, '') and upper not in (None, ''):
            result = sp.simplify(sp.integrate(_expr(value), (x, _point(lower), _point(upper))))
        else:
            result = sp.integrate(_expr(value), x)
            if result.has(sp.Integral):
                raise MathError('Primitive introuvable sous forme explicite.')
    else:  # limit
        point = _point(options.get('point', '0'))
        direction = options.get('direction') or '+-'
        if direction not in ('+', '-', '+-'):
            raise MathError('Direction invalide.')
        if point in (sp.oo, -sp.oo):
            direction = '+' if point == -sp.oo else '-'
        expr = _expr(value)
        try:
            result = sp.limit(expr, x, point, direction)
        except ValueError:
            result = sp.zoo
        if result == sp.zoo or (direction == '+-' and result.has(sp.zoo)):
            left, right = sp.limit(expr, x, point, '-'), sp.limit(expr, x, point, '+')
            text = (rf'\lim_{{{latex(x)} \to {latex(point)}^-}} = {latex(left)}, \quad '
                    rf'\lim_{{{latex(x)} \to {latex(point)}^+}} = {latex(right)}')
            return {'latex': text, 'text': f'gauche {left}, droite {right}'}
    return {'latex': latex(result), 'text': str(result)}


def _child(queue, action, expression, options):
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (MEMORY_LIMIT, MEMORY_LIMIT))
    except (ImportError, ValueError, OSError):
        pass
    try:
        queue.put({'ok': True, **_run(action, expression, options)})
    except (ParseError, MathError) as exc:
        queue.put({'ok': False, 'error': str(exc)})
    except MemoryError:
        queue.put({'ok': False, 'error': 'Calcul trop lourd.'})
    except Exception:  # noqa: BLE001 — SymPy peut lever bien des choses
        queue.put({'ok': False, 'error': 'Calcul impossible pour cette expression.'})


def compute(action, expression, timeout=TIMEOUT_SECONDS, **options):
    options = {k: (str(v)[:200] if v is not None else None) for k, v in options.items()}
    # « forkserver » : sûr même depuis un serveur multi-fils (fork y peut bloquer l'enfant).
    method = 'forkserver' if 'forkserver' in multiprocessing.get_all_start_methods() else 'spawn'
    context = multiprocessing.get_context(method)
    queue = context.Queue()
    process = context.Process(target=_child, args=(queue, action, expression, options), daemon=True)
    process.start()
    process.join(timeout)
    if process.is_alive():
        process.kill()
        process.join(1)
        return {'ok': False, 'error': 'Calcul trop long : simplifiez l’expression.'}
    try:
        return queue.get(timeout=1)
    except Exception:  # noqa: BLE001
        return {'ok': False, 'error': 'Calcul trop lourd.'}
