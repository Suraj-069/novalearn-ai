"""Deterministic evaluation of numerical-question formulas. Only arithmetic and a few math functions are allowed."""
import ast
import math
import operator

_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.Pow: operator.pow}
_FUNCS = {"sqrt": math.sqrt, "ln": math.log, "log": math.log10, "exp": math.exp, "sin": math.sin, "cos": math.cos, "tan": math.tan, "abs": abs}
_CONSTS = {"pi": math.pi, "e": math.e}


class EvalError(ValueError):
    pass


def safe_eval(expr: str, variables: dict[str, float]) -> float:
    if len(expr) > 200:
        raise EvalError("expression too long")
    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except SyntaxError as e:
        raise EvalError("invalid expression") from e

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
            return float(n.value)
        if isinstance(n, ast.Name):
            if n.id in variables:
                return float(variables[n.id])
            if n.id in _CONSTS:
                return _CONSTS[n.id]
            raise EvalError(f"unknown name '{n.id}'")
        if isinstance(n, ast.BinOp) and type(n.op) in _BIN:
            a, b = ev(n.left), ev(n.right)
            if isinstance(n.op, ast.Pow) and abs(b) > 12:
                raise EvalError("exponent too large")
            return _BIN[type(n.op)](a, b)
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
            return -ev(n.operand) if isinstance(n.op, ast.USub) else ev(n.operand)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in _FUNCS and len(n.args) == 1 and not n.keywords:
            return _FUNCS[n.func.id](ev(n.args[0]))
        raise EvalError("disallowed syntax")

    try:
        val = ev(tree)
    except (ZeroDivisionError, OverflowError, ValueError) as e:
        raise EvalError(str(e)) from e
    if not math.isfinite(val):
        raise EvalError("non-finite result")
    return val
