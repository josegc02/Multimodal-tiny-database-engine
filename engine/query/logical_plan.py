"""Construcción y validación de un árbol lógico desde el AST del parser."""

from dataclasses import dataclass, fields, replace
import math
import struct

from engine.query import ast
from engine.query.catalog import Catalog
from engine.query.errors import SQLSemanticError


@dataclass(frozen=True)
class LogicalPlan:
    operation: str
    children: tuple = ()
    options: tuple = ()

    def get(self, name, default=None):
        return dict(self.options).get(name, default)

    def to_dict(self):
        def convert(value):
            if isinstance(value, ast.Node):
                return value.to_dict()
            if isinstance(value, tuple):
                return [convert(item) for item in value]
            return value
        return {"operation": self.operation,
                "options": {name: convert(value) for name, value in self.options},
                "children": [child.to_dict() for child in self.children]}


def node(operation, *children, **options):
    return LogicalPlan(operation, tuple(children), tuple(options.items()))


def expression_children(expression):
    for field in fields(expression):
        value = getattr(expression, field.name)
        if isinstance(value, ast.Expression):
            yield value
        elif isinstance(value, tuple):
            yield from (item for item in value if isinstance(item, ast.Expression))


def map_children(expression, function):
    changes = {}
    for field in fields(expression):
        value = getattr(expression, field.name)
        if isinstance(value, ast.Expression):
            changes[field.name] = function(value)
        elif isinstance(value, tuple):
            changes[field.name] = tuple(function(item) if isinstance(item, ast.Expression) else item for item in value)
    return replace(expression, **changes)


def column_key(column: ast.ColumnRef) -> str:
    # Codificación sin colisiones incluso para identificadores citados con '.'.
    return column.name if column.table is None else f"c:{len(column.table)}:{column.table}{column.name}"


def output_name(expression):
    if isinstance(expression, ast.ColumnRef):
        return f"{expression.table}.{expression.name}" if expression.table else expression.name
    if isinstance(expression, ast.Star):
        return "*"
    if isinstance(expression, ast.AggregateCall):
        distinct = "distinct " if expression.distinct else ""
        return f"{expression.function.lower()}({distinct}{output_name(expression.argument)})"
    if isinstance(expression, ast.Literal):
        return str(expression.value)
    return repr(expression)


def normalize_insert(binding, columns, rows):
    """Valida el lote completo antes de escribir y respeta el formato de Schema."""
    schema = binding.storage.schema
    if len(columns) != len(set(columns)) or set(columns) != set(schema.fields):
        raise SQLSemanticError("INSERT debe proporcionar cada columna del schema una vez; no hay defaults")
    result = []
    for values in rows:
        if len(values) != len(columns):
            raise SQLSemanticError("Cantidad de valores incorrecta en INSERT")
        record = dict(zip(columns, (value.value for value in values)))
        for name, kind in zip(schema.fields, schema.types):
            value = record[name]
            if (kind == "int" and type(value) is not int
                    or kind == "float" and type(value) not in (int, float)
                    or kind == "str" and type(value) is not str):
                raise SQLSemanticError(f"Tipo inválido para {name!r}: se requiere {kind}; storage no admite NULL")
            if type(value) is float and not math.isfinite(value):
                raise SQLSemanticError(f"Valor no finito para {name!r}")
        try:
            result.append(schema.deserialize(schema.serialize(record)))
        except (ValueError, TypeError, OverflowError, struct.error) as exc:
            raise SQLSemanticError(f"El registro no puede serializarse: {exc}") from exc
    return result


class LogicalPlanner:
    def __init__(self, catalog: Catalog):
        self.catalog = catalog

    def _scope(self, tables):
        scope = {}
        for table in tables:
            qualifier = table.alias or table.name
            if qualifier in scope:
                raise SQLSemanticError(f"Alias de tabla repetido: {qualifier}")
            scope[qualifier] = self.catalog.table(table.name).storage.schema.fields
        return scope

    def _bind(self, expression, scope, *, aggregates=False):
        if isinstance(expression, ast.ColumnRef):
            qualifiers = [q for q, names in scope.items() if expression.name in names
                          and (expression.table is None or expression.table == q)]
            if len(qualifiers) != 1:
                reason = "ambigua" if qualifiers else "inexistente"
                raise SQLSemanticError(f"Columna {reason}: {output_name(expression)}")
            return ast.ColumnRef(expression.name, qualifiers[0])
        if isinstance(expression, ast.AggregateCall):
            if not aggregates:
                raise SQLSemanticError("No se permite un agregado en este contexto")
            if expression.distinct:
                raise SQLSemanticError("La ejecución de agregados DISTINCT aún no está implementada")
            if isinstance(expression.argument, ast.Star):
                if expression.function != "COUNT":
                    raise SQLSemanticError("Solo COUNT admite '*'")
                return expression
            return replace(expression, argument=self._bind(expression.argument, scope))
        if isinstance(expression, ast.Star):
            raise SQLSemanticError("Comodín fuera de la proyección")
        return map_children(expression, lambda child: self._bind(child, scope, aggregates=aggregates))

    def plan(self, statement: ast.Statement) -> LogicalPlan:
        if isinstance(statement, ast.SelectStatement):
            return self._select(statement)
        if isinstance(statement, ast.InsertStatement):
            binding = self.catalog.table(statement.table)
            columns = statement.columns or tuple(binding.storage.schema.fields)
            normalize_insert(binding, columns, statement.values)
            return node("Insert", table=statement.table, columns=columns, values=statement.values)
        if isinstance(statement, ast.DeleteStatement):
            scope = self._scope((statement.table,))
            predicate = self._bind(statement.where, scope) if statement.where is not None else None
            source = node("Scan", table=statement.table, predicate=predicate)
            if predicate is not None:
                source = node("Filter", source, predicate=predicate)
            return node("Delete", source, table=statement.table)
        if isinstance(statement, ast.TransactionStatement):
            raise SQLSemanticError("Las transacciones requieren un TransactionManager; todavía no están implementadas")
        raise SQLSemanticError("Sentencia no soportada")

    def _select(self, statement):
        tables = (statement.from_table,) + tuple(join.table for join in statement.joins)
        scope = self._scope(tables)
        where = self._bind(statement.where, scope) if statement.where is not None else None
        plan = node("Scan", table=statement.from_table, predicate=where if not statement.joins else None)
        joined_scope = self._scope((statement.from_table,))
        for join in statement.joins:
            joined_scope.update(self._scope((join.table,)))
            predicate = self._bind(join.condition, joined_scope)
            right_qualifier = join.table.alias or join.table.name
            pairs = self._join_pairs(predicate, right_qualifier)
            if not pairs:
                raise SQLSemanticError("JOIN requiere al menos una igualdad entre columnas de ambos lados")
            plan = node("Join", plan, node("Scan", table=join.table), predicate=predicate, pairs=tuple(pairs))
        if where is not None:
            plan = node("Filter", plan, predicate=where)

        projections = []
        aliases = {}
        for item in statement.columns:
            if isinstance(item.expression, ast.Star):
                selected = scope if item.expression.table is None else {
                    item.expression.table: scope.get(item.expression.table)}
                if any(names is None for names in selected.values()):
                    raise SQLSemanticError("Tabla o alias inexistente en el comodín")
                for qualifier, names in selected.items():
                    for name in names:
                        label = name if len(scope) == 1 else f"{qualifier}.{name}"
                        projections.append((label, ast.ColumnRef(name, qualifier)))
            else:
                bound = self._bind(item.expression, scope, aggregates=True)
                label = item.alias or output_name(item.expression)
                projections.append((label, bound))
                if item.alias:
                    aliases[item.alias] = bound
        if len({label for label, _ in projections}) != len(projections):
            raise SQLSemanticError("La salida tiene nombres repetidos; usa aliases AS diferentes")

        group_by = tuple(self._bind(expr, scope) for expr in statement.group_by)
        having = self._bind(statement.having, scope, aggregates=True) if statement.having is not None else None
        order_by = []
        for item in statement.order_by:
            expression = item.expression
            if isinstance(expression, ast.ColumnRef) and expression.table is None and expression.name in aliases:
                expression = aliases[expression.name]
            elif isinstance(expression, ast.Literal) and type(expression.value) is int:
                if not 1 <= expression.value <= len(projections):
                    raise SQLSemanticError("Posición de ORDER BY fuera de la proyección")
                expression = projections[expression.value - 1][1]
            else:
                expression = self._bind(expression, scope, aggregates=True)
            order_by.append(replace(item, expression=expression))

        aggregates = []
        def collect(expr):
            if isinstance(expr, ast.AggregateCall):
                if expr not in aggregates:
                    aggregates.append(expr)
                return
            for child in expression_children(expr):
                collect(child)
        for expression in [expr for _, expr in projections] + [item.expression for item in order_by] + ([having] if having else []):
            collect(expression)
        if group_by or aggregates or having is not None:
            def grouped(expr):
                if expr in group_by:
                    return ast.ColumnRef(f"$group{group_by.index(expr)}")
                if isinstance(expr, ast.AggregateCall):
                    return ast.ColumnRef(f"$agg{aggregates.index(expr)}")
                if isinstance(expr, ast.ColumnRef):
                    raise SQLSemanticError(f"Columna fuera de GROUP BY: {output_name(expr)}")
                return map_children(expr, grouped)
            plan = node("Aggregate", plan, group_by=group_by, aggregates=tuple(aggregates))
            projections = [(label, grouped(expr)) for label, expr in projections]
            order_by = [replace(item, expression=grouped(item.expression)) for item in order_by]
            if having is not None:
                plan = node("Filter", plan, predicate=grouped(having))
        if statement.distinct:
            selected = tuple(expr for _, expr in projections)
            if any(item.expression not in selected for item in order_by):
                raise SQLSemanticError("ORDER BY con DISTINCT debe referirse a expresiones seleccionadas")
            plan = node("Distinct", plan, expressions=selected)
        if order_by:
            plan = node("Sort", plan, order_by=tuple(order_by))
        plan = node("Project", plan, columns=tuple(projections))
        if statement.limit is not None or statement.offset is not None:
            plan = node("Limit", plan, limit=statement.limit, offset=statement.offset or 0)
        return plan

    def _join_pairs(self, expression, right):
        if isinstance(expression, ast.BinaryOp) and expression.operator == "AND":
            return self._join_pairs(expression.left, right) + self._join_pairs(expression.right, right)
        if (isinstance(expression, ast.BinaryOp) and expression.operator == "="
                and isinstance(expression.left, ast.ColumnRef) and isinstance(expression.right, ast.ColumnRef)):
            left, other = expression.left, expression.right
            if (left.table == right) != (other.table == right):
                return [(other, left)] if left.table == right else [(left, other)]
        return []
