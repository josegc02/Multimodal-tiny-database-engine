"""Evaluación explícita de expresiones SQL, incluyendo lógica de tres valores."""

import operator
import re

from engine.query import ast
from engine.query.errors import SQLExecutionError
from engine.query.logical_plan import column_key


def truth(value):
    if value is not None and type(value) is not bool:
        raise SQLExecutionError("La condición debe producir TRUE, FALSE o NULL")
    return value


def _and(left, right):
    return False if left is False or right is False else None if left is None or right is None else True


def _compare(op, left, right):
    if left is None or right is None:
        return None
    compatible = type(left) is type(right) or (type(left) in (int, float) and type(right) in (int, float))
    if op in ("=", "!=") and not compatible:
        return op == "!="
    return {"=": operator.eq, "!=": operator.ne, "<": operator.lt, "<=": operator.le,
            ">": operator.gt, ">=": operator.ge}[op](left, right)


def evaluate(expression, row):
    try:
        return _evaluate(expression, row)
    except SQLExecutionError:
        raise
    except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
        raise SQLExecutionError(f"No se pudo evaluar la expresión SQL: {exc}") from exc


def _evaluate(expression, row):
    if isinstance(expression, ast.Literal):
        return expression.value
    if isinstance(expression, ast.ColumnRef):
        return row[column_key(expression)]
    if isinstance(expression, ast.UnaryOp):
        value = evaluate(expression.operand, row)
        if expression.operator == "NOT":
            value = truth(value)
            return None if value is None else not value
        if value is None:
            return None
        if type(value) not in (int, float):
            raise SQLExecutionError("El signo unario requiere un número")
        return -value if expression.operator == "-" else value
    if isinstance(expression, ast.IsNull):
        result = evaluate(expression.expression, row) is None
        return not result if expression.negated else result
    if isinstance(expression, ast.Between):
        value = evaluate(expression.expression, row)
        lower, upper = evaluate(expression.lower, row), evaluate(expression.upper, row)
        result = _and(_compare(">=", value, lower), _compare("<=", value, upper))
        return not result if expression.negated and result is not None else result
    if isinstance(expression, ast.InList):
        value = evaluate(expression.expression, row)
        result = False
        for candidate in expression.values:
            comparison = _compare("=", value, evaluate(candidate, row))
            if comparison is True:
                result = True
                break
            if comparison is None:
                result = None
        return not result if expression.negated and result is not None else result
    if isinstance(expression, ast.BinaryOp):
        op = expression.operator
        left = evaluate(expression.left, row)
        if op in ("AND", "OR"):
            left = truth(left)
            if op == "AND" and left is False:
                return False
            if op == "OR" and left is True:
                return True
            right = truth(evaluate(expression.right, row))
            if op == "AND":
                return _and(left, right)
            return True if right is True else None if left is None or right is None else False
        right = evaluate(expression.right, row)
        if op in {"=", "!=", "<", "<=", ">", ">="}:
            return _compare(op, left, right)
        if left is None or right is None:
            return None
        if op in ("LIKE", "NOT LIKE"):
            if not isinstance(left, str) or not isinstance(right, str):
                raise SQLExecutionError("LIKE requiere strings")
            pattern = "".join(".*" if char == "%" else "." if char == "_" else re.escape(char) for char in right)
            matched = re.fullmatch(pattern, left, re.DOTALL) is not None
            return not matched if op == "NOT LIKE" else matched
        if type(left) not in (int, float) or type(right) not in (int, float):
            raise SQLExecutionError("La aritmética requiere valores numéricos")
        return {"+": operator.add, "-": operator.sub, "*": operator.mul,
                "/": operator.truediv, "%": operator.mod}[op](left, right)
    raise SQLExecutionError(f"Expresión no ejecutable: {type(expression).__name__}")
