"""Exact, intentionally narrow linear-equation check. Never evaluates user code."""
import ast
import re
from fractions import Fraction


def _linear(expression):
    expression = expression.replace('−', '-').replace('×', '*').replace('÷', '/')
    expression = expression.replace('\\cdot', '*').replace('\\times', '*')
    expression = re.sub(r'(?<=\d)\s*(?=x)', '*', expression)
    expression = re.sub(r'(?<=[\dx)])\s*(?=\()', '*', expression)
    if len(expression) > 250 or not re.fullmatch(r'[\dx\s.+*/()\-]+', expression):
        raise ValueError()
    node = ast.parse(expression.strip(), mode='eval')
    if sum(1 for _ in ast.walk(node)) > 80:
        raise ValueError()

    def walk(n):
        if isinstance(n, ast.Expression):
            return walk(n.body)
        if isinstance(n, ast.Constant) and type(n.value) in (int, float):
            value = Fraction(str(n.value))
            if abs(value) > 10**12:
                raise ValueError()
            return Fraction(0), value
        if isinstance(n, ast.Name) and n.id == 'x':
            return Fraction(1), Fraction(0)
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
            a, b = walk(n.operand)
            return (-a, -b) if isinstance(n.op, ast.USub) else (a, b)
        if isinstance(n, ast.BinOp):
            a, b = walk(n.left)
            c, d = walk(n.right)
            if isinstance(n.op, ast.Add):
                return a+c, b+d
            if isinstance(n.op, ast.Sub):
                return a-c, b-d
            if isinstance(n.op, ast.Mult) and not (a and c):
                return a*d+b*c, b*d
            if isinstance(n.op, ast.Div) and not c and d:
                return a/d, b/d
        raise ValueError()
    return walk(node)


def _solution(equation):
    left, right = equation.strip().strip('$').split('=')
    a, b = _linear(left)
    c, d = _linear(right)
    if a == c:
        raise ValueError()
    return (d-b)/(a-c)


def check_linear(context):
    """Return None for unsupported mathematics, not a false correctness claim."""
    selected = context.get('selected_object') or {}
    attempt = selected.get('latex') or selected.get('text') or ''
    original = context.get('exercise', '')
    if not original:
        original = next((o.get('latex') or o.get('text') for o in context['whiteboard_content']
                         if o['id'] != selected.get('id') and '=' in (o.get('latex') or o.get('text') or '')), '')
    try:
        expected, actual = _solution(original), _solution(attempt)
    except (ValueError, SyntaxError, ZeroDivisionError, OverflowError, RecursionError):
        return None
    return {'method': 'Calcul rationnel exact : équations linéaires en x',
            'original': original, 'attempt': attempt, 'equivalent': expected == actual}
