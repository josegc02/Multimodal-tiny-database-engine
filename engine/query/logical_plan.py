"""Construcción y validación de un árbol lógico desde el AST del parser."""

from dataclasses import dataclass, fields, replace
from functools import reduce
import math
import struct

from engine.query import ast
from engine.query.catalog import Catalog
from engine.query.errors import SQLSemanticError
from engine.spatial.geometry import Point, Polygon


SCORE_COLUMN = "$score"  # campo interno de cada fila con el valor de SCORE()
SIMILARITY_COLUMN = "$similarity"  # campo interno con el valor de SIMILARITY_SCORE()
SIMILAR_TO_PLACEMENT = "SIMILAR_TO solo se admite una vez en el WHERE de un SELECT sobre una tabla, unido con AND"


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


def uses(expression, kind):
    """Indica si la expresión contiene un nodo de ese tipo."""
    pending = [expression]
    while pending:
        current = pending.pop()
        if isinstance(current, kind):
            return True
        pending.extend(expression_children(current))
    return False


def annotate_scan(plan, **options):
    """Agrega opciones a los Scan del plan."""
    if plan.operation == "Scan":
        return replace(plan, options=plan.options + tuple(options.items()))
    return replace(plan, children=tuple(annotate_scan(child, **options) for child in plan.children))


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
    if isinstance(expression, ast.SpatialCall):
        return f"{expression.function.lower()}({', '.join(output_name(a) for a in expression.arguments)})"
    if isinstance(expression, ast.ScoreCall):
        return "score()"
    if isinstance(expression, ast.SimilarityScoreCall):
        return "similarity_score()"
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
                    or kind in ("str", "text", "image", "audio") and type(value) is not str
                    or kind == "point" and not isinstance(value, Point)):
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
            schema = self.catalog.table(table.name).storage.schema
            scope[qualifier] = dict(zip(schema.fields, schema.types))
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
            if isinstance(expression.argument, ast.Star):
                if expression.distinct:
                    raise SQLSemanticError("DISTINCT requiere una expresión, no '*'")
                if expression.function != "COUNT":
                    raise SQLSemanticError("Solo COUNT admite '*'")
                return expression
            return replace(expression, argument=self._bind(expression.argument, scope))
        if isinstance(expression, ast.Star):
            raise SQLSemanticError("Comodín fuera de la proyección")
        if isinstance(expression, ast.MatchCall):
            raise SQLSemanticError("MATCH solo se admite una vez en el WHERE de un SELECT sobre una tabla, unido con AND")
        if isinstance(expression, ast.SimilarCall):
            raise SQLSemanticError(SIMILAR_TO_PLACEMENT)
        if isinstance(expression, ast.SpatialCall):
            if expression.function not in ("DISTANCIA", "WITHIN") or len(expression.arguments) != 2:
                raise SQLSemanticError("Función espacial inválida")
            bound = map_children(expression, lambda child: self._bind(child, scope, aggregates=aggregates))
            if bound.metric not in (None, "haversine", "euclidean"):
                raise SQLSemanticError("Métrica espacial inválida")
            for arg, expected in zip(bound.arguments, ("point", "point" if bound.function == "DISTANCIA" else "polygon")):
                if isinstance(arg, ast.ColumnRef):
                    kind = scope[arg.table][arg.name]
                elif isinstance(arg, ast.Literal):
                    kind = "point" if isinstance(arg.value, Point) else "polygon" if isinstance(arg.value, Polygon) else None
                else:
                    kind = None
                if kind != expected:
                    raise SQLSemanticError(f"{bound.function} requiere argumentos {expected.upper()}")
            return bound
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
            if predicate is not None and uses(predicate, ast.ScoreCall):
                raise SQLSemanticError("SCORE() requiere un MATCH en un SELECT")
            if predicate is not None and uses(predicate, ast.SimilarityScoreCall):
                raise SQLSemanticError("SIMILARITY_SCORE() requiere un SIMILAR_TO en un SELECT")
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
        match, where = self._split_match(statement, scope)
        similar, where = self._split_similar(statement, where, scope)
        if match is not None and similar is not None:
            raise SQLSemanticError("MATCH y SIMILAR_TO no se pueden combinar en la misma consulta")
        where = self._bind(where, scope) if where is not None else None
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
        grouping = bool(group_by or aggregates) or having is not None
        scored = [expr for _, expr in projections] + [item.expression for item in order_by]
        scored += [expr for expr in (where, having) if expr is not None]
        if any(uses(expr, ast.ScoreCall) for expr in scored):
            if match is None:
                raise SQLSemanticError("SCORE() requiere un MATCH en el WHERE")
            if grouping:
                raise SQLSemanticError("SCORE() no se admite con agregación")
        # El recorrido de texto ya entrega las filas de mayor a menor puntaje.
        ranked = (match is not None and not statement.distinct and len(order_by) == 1
                  and isinstance(order_by[0].expression, ast.ScoreCall) and order_by[0].direction == "DESC")
        if match is not None:
            # Con otro filtro, otro orden o agregación, recortar antes perdería filas válidas.
            top_k = None
            if (statement.limit is not None and where is None and not statement.distinct and not grouping
                    and (ranked or not order_by)):
                top_k = statement.limit + (statement.offset or 0)
            plan = annotate_scan(plan, text_match=match, text_k=top_k)
        if any(uses(expr, ast.SimilarityScoreCall) for expr in scored):
            if similar is None:
                raise SQLSemanticError("SIMILARITY_SCORE() requiere un SIMILAR_TO en el WHERE")
            if grouping:
                raise SQLSemanticError("SIMILARITY_SCORE() no se admite con agregación")
        if similar is not None:
            # El recorrido vectorial entrega los k vecinos de mayor a menor similitud.
            ranked = (not statement.distinct and len(order_by) == 1
                      and isinstance(order_by[0].expression, ast.SimilarityScoreCall)
                      and order_by[0].direction == "DESC")
            # Un LIMIT menor que k recorta la búsqueda solo si no puede perder filas válidas.
            vector_k = similar.k
            if (statement.limit is not None and where is None and not statement.distinct and not grouping
                    and (ranked or not order_by)):
                vector_k = min(vector_k, statement.limit + (statement.offset or 0))
            plan = annotate_scan(plan, vector_search=similar, vector_k=vector_k)
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
        if order_by and not ranked:
            # El LIMIT va justo encima: un recorrido ordenado puede detenerse antes.
            needed = None if statement.limit is None else statement.limit + (statement.offset or 0)
            plan = node("Sort", plan, order_by=tuple(order_by), limit=needed)
        # Top-k espacial solo para una tabla, sin agregación ni DISTINCT y una
        # única clave de orden ASC. Otros casos conservan el sort SQL completo.
        if (statement.limit is not None and len(order_by) == 1 and order_by[0].direction == "ASC"
                and not statement.joins and not statement.distinct and not group_by
                and not aggregates and having is None and isinstance(order_by[0].expression, ast.SpatialCall)
                and order_by[0].expression.function == "DISTANCIA"):
            def annotate(current):
                if current.operation == "Scan":
                    return node("Scan", table=current.get("table"), predicate=current.get("predicate"),
                                spatial_order=order_by[0].expression,
                                spatial_k=statement.limit + (statement.offset or 0))
                return replace(current, children=tuple(annotate(child) for child in current.children))
            plan = annotate(plan)
        plan = node("Project", plan, columns=tuple(projections))
        if statement.limit is not None or statement.offset is not None:
            plan = node("Limit", plan, limit=statement.limit, offset=statement.offset or 0)
        return plan

    def _split_match(self, statement, scope):
        """Separa el MATCH del WHERE: (MATCH enlazado o None, WHERE sin él).

        Solo un término unido con AND equivale a filtrar por el índice. Dentro de
        OR o NOT queda en el WHERE y _bind lo rechaza.
        """
        terms = []
        pending = [statement.where] if statement.where is not None else []
        while pending:
            term = pending.pop()
            if isinstance(term, ast.BinaryOp) and term.operator == "AND":
                pending += [term.right, term.left]
            else:
                terms.append(term)
        matches = [term for term in terms if isinstance(term, ast.MatchCall)]
        if not matches:
            return None, statement.where
        if len(matches) > 1 or statement.joins:
            raise SQLSemanticError("MATCH solo se admite una vez en el WHERE de un SELECT sobre una tabla, unido con AND")
        column = self._bind(matches[0].column, scope)
        if scope[column.table][column.name] not in ("str", "text"):
            raise SQLSemanticError(f"MATCH requiere una columna TEXT o VARCHAR: {column.name}")
        registered = self.catalog.table(statement.from_table.name).indexes.get(column.name)
        if registered is None or not registered.metadata.text:
            raise SQLSemanticError(f"MATCH requiere un índice SPIMI sobre {column.name}")
        rest = [term for term in terms if term is not matches[0]]
        where = reduce(lambda left, right: ast.BinaryOp("AND", left, right), rest) if rest else None
        return replace(matches[0], column=column), where

    def _split_similar(self, statement, where, scope):
        """Separa el SIMILAR_TO del WHERE y lo enlaza con su columna, índice y métrica.

        Las demás condiciones filtran los k vecinos que devuelve el índice.
        """
        terms = []
        pending = [where] if where is not None else []
        while pending:
            term = pending.pop()
            if isinstance(term, ast.BinaryOp) and term.operator == "AND":
                pending += [term.right, term.left]
            else:
                terms.append(term)
        calls = [term for term in terms if isinstance(term, ast.SimilarCall)]
        if not calls:
            return None, where
        if len(calls) > 1 or statement.joins:
            raise SQLSemanticError(SIMILAR_TO_PLACEMENT)
        call = calls[0]
        table = statement.from_table.name
        indexes = self.catalog.table(table).indexes
        method = call.method.upper()
        if call.column is not None:
            column = self._bind(call.column, scope)
            if scope[column.table][column.name] not in ("image", "audio"):
                raise SQLSemanticError(f"SIMILAR_TO requiere una columna IMAGE o AUDIO: {column.name}")
            registered = indexes.get(column.name)
            if registered is None or not registered.metadata.vector or registered.index.method != call.method:
                raise SQLSemanticError(f"SIMILAR_TO USING {method} requiere un índice {method} sobre {column.name}")
        else:
            candidates = [name for name, registered in indexes.items()
                          if registered.metadata.vector and registered.index.method == call.method]
            if len(candidates) != 1:
                reason = "no tiene" if not candidates else "tiene más de una columna con"
                raise SQLSemanticError(f"La tabla {table} {reason} un índice {method}; "
                                       "indica la columna: SIMILAR_TO(columna, 'archivo', k=N)")
            column = ast.ColumnRef(candidates[0], statement.from_table.alias or table)
            registered = indexes[column.name]
        metric = registered.index.metric
        if call.metric is not None and call.metric != metric:
            raise SQLSemanticError(
                f"El índice {registered.metadata.name} usa METRIC={metric}; "
                f"crea otro con USING {method} WITH (METRIC = {call.metric}) para usar {call.metric}")
        rest = [term for term in terms if term is not call]
        where = reduce(lambda left, right: ast.BinaryOp("AND", left, right), rest) if rest else None
        return replace(call, column=column, metric=metric), where

    def _join_pairs(self, expression, right):
        if isinstance(expression, ast.BinaryOp) and expression.operator == "AND":
            return self._join_pairs(expression.left, right) + self._join_pairs(expression.right, right)
        if (isinstance(expression, ast.BinaryOp) and expression.operator == "="
                and isinstance(expression.left, ast.ColumnRef) and isinstance(expression.right, ast.ColumnRef)):
            left, other = expression.left, expression.right
            if (left.table == right) != (other.table == right):
                return [(other, left)] if left.table == right else [(left, other)]
        return []
