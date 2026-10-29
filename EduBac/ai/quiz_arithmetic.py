"""Bounded exact constants only. AST is inspected, never executed or compiled."""
import ast
import re
from fractions import Fraction


def constant_value(expression):
    try:
        if len(expression) > 500:
            return None
        expression = expression.replace("−", "-").replace("×", "*").replace("÷", "/")
        expression = expression.replace(r"\cdot", "*").replace(r"\times", "*").replace(r"\div", "/")
        expression = expression.replace(r"\left", "").replace(r"\right", "")
        for _ in range(4):
            expression = re.sub(r"\\[dt]?frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}",
                                r"((\1)/(\2))", expression)
        expression = expression.replace("{", "(").replace("}", ")").replace("^", "**")
        expression = re.sub(r"(?<=[\d)])\s*(?=\()", "*", expression)
        expression = re.sub(r"(?<=\))\s*(?=\d)", "*", expression)
        if not re.fullmatch(r"[\d\s.+*/()\-]+", expression):
            return None
        tree = ast.parse(expression.strip(), mode="eval")
        if sum(1 for _ in ast.walk(tree)) > 100:
            return None

        def walk(node):
            if isinstance(node, ast.Expression):
                value = walk(node.body)
            elif isinstance(node, ast.Constant) and type(node.value) in (int, float):
                value = Fraction(str(node.value))
            elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                value = walk(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
            elif isinstance(node, ast.BinOp):
                left, right = walk(node.left), walk(node.right)
                if isinstance(node.op, ast.Add):
                    value = left + right
                elif isinstance(node.op, ast.Sub):
                    value = left - right
                elif isinstance(node.op, ast.Mult):
                    value = left * right
                elif isinstance(node.op, ast.Div):
                    value = left / right
                elif isinstance(node.op, ast.Pow) and right.denominator == 1 and abs(right) <= 12:
                    value = left ** int(right)
                else:
                    raise ValueError()
            else:
                raise ValueError()
            if value.numerator.bit_length() > 256 or value.denominator.bit_length() > 256:
                raise ValueError()
            return value
        return walk(tree)
    except (ValueError, SyntaxError, TypeError, ZeroDivisionError, OverflowError, RecursionError):
        return None
