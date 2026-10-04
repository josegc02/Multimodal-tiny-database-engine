"""EXPLAIN y EXPLAIN ANALYZE con el formato de texto de PostgreSQL.

Convierte el plan lógico + las decisiones del optimizador en un árbol como el
de psql:

    Sort  (cost=0.00..95.00 rows=333)
      Sort Key: id
      ->  Seq Scan on alumnos  (cost=0.00..25.00 rows=333)
            Filter: (nota >= 14)

Los costos son los del modelo de este motor (páginas leídas estimadas), no los
de PostgreSQL. Con ANALYZE se agregan los valores reales medidos por operador
(tiempo hasta la primera fila..última fila, filas y ejecuciones).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engine.query import ast
from engine.query.sql_optimizer import base_scan


@dataclass
class PlanNode:
    label: str
    cost: float
    rows: float
    details: list = field(default_factory=list)
    children: list = field(default_factory=list)
    # Claves del perfil (id de nodos lógicos) cuyas filas de salida son las de este nodo,
    # en orden de preferencia (el Filter plegado primero, luego el operador base).
    keys: list = field(default_factory=list)
    input_key: int | None = None       # filas antes del Filter: "Rows Removed by Filter"
    actual: dict | None = None         # perfil explícito (INSERT / DELETE)
    names: dict = field(default_factory=dict)  # $groupN / $aggN -> texto (para HAVING)
    consumed: tuple = ()               # condiciones ya resueltas por el índice
    is_sort: bool = False


def sql_text(expression, qualified=False, names=None):
    """Expresión SQL legible, con paréntesis como PostgreSQL."""
    names = names or {}

    def text(e):
        if isinstance(e, ast.ColumnRef):
            if e.table is None and e.name in names:
                return names[e.name]
            return f"{e.table}.{e.name}" if qualified and e.table else e.name
        if isinstance(e, ast.Literal):
            if isinstance(e.value, str):
                return "'" + e.value.replace("'", "''") + "'"
            if e.value is None:
                return "NULL"
            if isinstance(e.value, bool):
                return "true" if e.value else "false"
            return str(e.value)
        if isinstance(e, ast.Star):
            return "*"
        if isinstance(e, ast.AggregateCall):
            return f"{e.function.lower()}({'DISTINCT ' if e.distinct else ''}{text(e.argument)})"
        if isinstance(e, ast.UnaryOp):
            if e.operator == "NOT":
                return f"(NOT {text(e.operand)})"
            return f"{e.operator}{text(e.operand)}"
        if isinstance(e, ast.BinaryOp):
            return f"({text(e.left)} {e.operator} {text(e.right)})"
        if isinstance(e, ast.Between):
            return f"({text(e.expression)} {'NOT ' if e.negated else ''}BETWEEN {text(e.lower)} AND {text(e.upper)})"
        if isinstance(e, ast.InList):
            values = ", ".join(text(v) for v in e.values)
            return f"({text(e.expression)} {'NOT ' if e.negated else ''}IN ({values}))"
        if isinstance(e, ast.IsNull):
            return f"({text(e.expression)} IS {'NOT ' if e.negated else ''}NULL)"
        return str(e)

    return text(expression)


class PlanExplainer:
    def __init__(self, catalog, optimizer):
        self.catalog = catalog
        self.optimizer = optimizer
        self.costs = optimizer.costs
        self.qualified = False

    # ------------------------------------------------------------------
    # Construcción del árbol
    # ------------------------------------------------------------------

    def build(self, plan) -> PlanNode:
        self.qualified = self._count_scans(plan) > 1
        return self._build(plan)

    def _count_scans(self, plan):
        return (plan.operation == "Scan") + sum(self._count_scans(child) for child in plan.children)

    def _build(self, node, ordered=None) -> PlanNode:
        builder = getattr(self, f"_build_{node.operation.lower()}")
        return builder(node, ordered)

    def _text(self, expression, names=None):
        return sql_text(expression, self.qualified, names)

    def _build_project(self, node, ordered):
        return self._build(node.children[0], ordered)

    def _build_limit(self, node, ordered):
        child = self._build(node.children[0], ordered)
        limit, offset = node.get("limit"), node.get("offset") or 0
        rows = max(0.0, child.rows - offset)
        if limit is not None:
            rows = min(rows, limit)
        return PlanNode("Limit", child.cost, rows, children=[child], keys=[id(node)], names=child.names)

    def _build_sort(self, node, ordered):
        choice = self.optimizer.choice(node)
        if choice is not None and choice.algorithm == "index_order_scan":
            # El índice ya entrega el orden pedido: no hay nodo Sort (como en PostgreSQL).
            built = self._build(node.children[0], ordered=choice)
            built.keys = built.keys + [id(node)]
            return built
        child = self._build(node.children[0])
        sort_key = ", ".join(self._text(item.expression, child.names) + (" DESC" if item.direction == "DESC" else "")
                             for item in node.get("order_by"))
        cost = child.cost + (choice.estimated_io if choice else 0)
        return PlanNode("Sort", cost, child.rows, [f"Sort Key: {sort_key}"], [child], [id(node)],
                        names=child.names, is_sort=True)

    def _build_aggregate(self, node, ordered):
        choice = self.optimizer.choice(node)
        groups, aggregates = node.get("group_by"), node.get("aggregates")
        if choice is not None and choice.algorithm == "index_group_by":
            label, child = "GroupAggregate", self._build(node.children[0], ordered=choice)
        else:
            label = "HashAggregate" if groups else "Aggregate"
            child = self._build(node.children[0])
        names = {f"$group{i}": self._text(g) for i, g in enumerate(groups)}
        names.update({f"$agg{i}": self._text(a) for i, a in enumerate(aggregates)})
        details = [f"Group Key: {', '.join(self._text(g) for g in groups)}"] if groups else []
        rows = 1.0 if not groups else max(1.0, min(child.rows, child.rows / 10 or 1))
        cost = child.cost + (choice.estimated_io if choice else 0)
        return PlanNode(label, cost, rows, details, [child], [id(node)], names=names)

    def _build_distinct(self, node, ordered):
        child = self._build(node.children[0], ordered)
        return PlanNode("Unique", child.cost, child.rows, ["Method: external sort"], [child], [id(node)],
                        names=child.names)

    def _build_filter(self, node, ordered):
        child = self._build(node.children[0], ordered)
        terms = list(self.optimizer._conjuncts(node.get("predicate")))
        remaining = [term for term in terms if term not in child.consumed]
        if remaining:
            predicate = remaining[0]
            for term in remaining[1:]:
                predicate = ast.BinaryOp("AND", predicate, term)
            child.details.append(f"Filter: {self._text(predicate, child.names)}")
            child.input_key = child.keys[0] if child.keys else None
            if not child.consumed and child.label.split(" ")[0] not in ("Seq", "Index"):
                child.rows = max(1.0, child.rows / 3)
        # Las filas de salida son las del Filter (si se ejecutó como operador propio).
        child.keys = [id(node)] + child.keys
        return child

    def _table_label(self, table):
        return table.name + (f" {table.alias}" if table.alias else "")

    def _build_scan(self, node, ordered):
        table = node.get("table")
        binding = self.catalog.table(table.name)
        qualifier = table.alias or table.name
        predicate = node.get("predicate")
        rows = self._scan_rows(binding.statistics, predicate, qualifier)
        details, consumed = [], ()
        if ordered is not None:
            label = (f"Index Scan{' Backward' if ordered.reverse else ''} using {ordered.index.name} "
                     f"on {self._table_label(table)}")
            cost = ordered.estimated_io
            rows = binding.statistics.rows if predicate is None else rows
        else:
            choice = self.optimizer.choice(node)
            cost = choice.estimated_io
            if choice.algorithm == "index_scan":
                label = f"Index Scan using {choice.index.name} on {self._table_label(table)}"
                column = ast.ColumnRef(choice.field, qualifier)
                details.append(f"Index Cond: ({self._text(column)} = {self._text(ast.Literal(choice.value))})")
                consumed = tuple(term for term in self.optimizer._conjuncts(predicate)
                                 if self._is_equality(term, choice.field, qualifier, choice.value))
            elif choice.algorithm == "index_range_scan":
                label = f"Index Scan using {choice.index.name} on {self._table_label(table)}"
                lower, upper, include_lower, include_upper = choice.value
                column = self._text(ast.ColumnRef(choice.field, qualifier))
                parts = []
                if lower is not None:
                    parts.append(f"({column} {'>=' if include_lower else '>'} {self._text(ast.Literal(lower))})")
                if upper is not None:
                    parts.append(f"({column} {'<=' if include_upper else '<'} {self._text(ast.Literal(upper))})")
                details.append(f"Index Cond: {parts[0] if len(parts) == 1 else '(' + ' AND '.join(parts) + ')'}")
                consumed = tuple(term for term in self.optimizer._conjuncts(predicate)
                                 if self._is_range_on(term, choice.field, qualifier))
            else:
                label = f"Seq Scan on {self._table_label(table)}"
        return PlanNode(label, cost, rows, details, [], [id(node)], consumed=consumed)

    def _is_equality(self, term, column, qualifier, value):
        return term in tuple(self._equality_terms(term, column, qualifier, value))

    def _equality_terms(self, term, column, qualifier, value):
        if isinstance(term, ast.BinaryOp) and term.operator == "=":
            for col, other in ((term.left, term.right), (term.right, term.left)):
                ok, constant = self.optimizer._constant(other)
                if isinstance(col, ast.ColumnRef) and col.name == column and col.table == qualifier \
                        and ok and constant == value:
                    yield term

    def _is_range_on(self, term, column, qualifier):
        if isinstance(term, ast.Between) and not term.negated:
            target = term.expression
            return isinstance(target, ast.ColumnRef) and target.name == column and target.table == qualifier \
                and self.optimizer._constant(term.lower)[0] and self.optimizer._constant(term.upper)[0]
        if isinstance(term, ast.BinaryOp) and term.operator in ("<", "<=", ">", ">="):
            for col, other in ((term.left, term.right), (term.right, term.left)):
                if isinstance(col, ast.ColumnRef) and col.name == column and col.table == qualifier \
                        and self.optimizer._constant(other)[0]:
                    return True
        return False

    def _scan_rows(self, stats, predicate, qualifier):
        rows = stats.rows
        if predicate is None or not rows:
            return float(rows)
        estimates = [rows / max(1, stats.distinct_values.get(f, 1))
                     for f, _ in self.optimizer._equalities(predicate, qualifier)]
        estimates += [rows * self.costs._range_fraction(stats, f, low, high)
                      for f, (low, high, _, _) in self.optimizer._ranges(predicate, qualifier).items()]
        return max(1.0, min(estimates) if estimates else rows / 3)

    def _build_join(self, node, ordered):
        choice = self.optimizer.choice(node)
        left = self._build(node.children[0])
        right_plan = node.children[1]
        right_table = right_plan.get("table")
        pairs = node.get("pairs")
        conditions = [ast.BinaryOp("=", l, r) for l, r in pairs]
        condition = " AND ".join(self._text(c) for c in conditions)
        extra = [term for term in self.optimizer._conjuncts(node.get("predicate"))
                 if not any(term == c or term == ast.BinaryOp("=", c.right, c.left) for c in conditions)]
        stats = self.catalog.table(right_table.name).statistics
        right_field = pairs[0][1].name
        rows = max(1.0, left.rows * stats.rows / max(1, stats.distinct_values.get(right_field, 1)))
        details = []
        if extra:
            predicate = extra[0]
            for term in extra[1:]:
                predicate = ast.BinaryOp("AND", predicate, term)
            details.append(f"Join Filter: {self._text(predicate)}")
        if choice.algorithm == "index_nested_loop_join":
            inner_rows = max(1.0, stats.rows / max(1, stats.distinct_values.get(right_field, 1)))
            inner = PlanNode(f"Index Scan using {choice.index.name} on {self._table_label(right_table)}",
                             choice.index.lookup_pages, inner_rows,
                             [f"Index Cond: ({self._text(pairs[0][1])} = {self._text(pairs[0][0])})"])
            return PlanNode("Nested Loop", left.cost + choice.estimated_io, rows, details, [left, inner], [id(node)])
        right = self._build(right_plan)
        hashed = PlanNode("Hash", right.cost, right.rows, [], [right], list(right.keys))
        return PlanNode("Hash Join", left.cost + right.cost + choice.estimated_io, rows,
                        [f"Hash Cond: {condition if len(conditions) == 1 else '(' + condition + ')'}"] + details,
                        [left, hashed], [id(node)])

    def _build_insert(self, node, ordered):
        return PlanNode(f"Insert on {node.get('table')}", 0.0, 0.0)

    def _build_delete(self, node, ordered):
        child = self._build(node.children[0])
        return PlanNode(f"Delete on {self._table_label(node.get('table'))}", child.cost, 0.0, children=[child])

    # ------------------------------------------------------------------
    # Salida en texto
    # ------------------------------------------------------------------

    def render(self, root, profile=None, stats=None):
        """Líneas del QUERY PLAN. Con `profile` (EXPLAIN ANALYZE) agrega lo medido."""
        analyze = profile is not None
        lines = []

        def actual(node):
            """(medición, clave usada) del nodo; (None, None) si no se ejecutó."""
            if node.actual is not None:
                return node.actual, None
            for key in node.keys:
                if key in profile:
                    return profile[key], key
            return None, None

        def emit(node, depth):
            prefix = "" if depth == 0 else " " * (6 * (depth - 1) + 2) + "->  "
            rows = 0 if node.rows <= 0 else max(1, round(node.rows))
            line = f"{prefix}{node.label}  (cost=0.00..{node.cost:.2f} rows={rows})"
            measured, used_key = actual(node) if analyze else (None, None)
            if analyze:
                if measured is None:
                    line += " (never executed)"
                else:
                    first = measured["first"] if measured["first"] is not None else measured["total"]
                    line += (f" (actual time={first * 1000:.3f}..{measured['total'] * 1000:.3f} "
                             f"rows={measured['rows']} loops={max(1, measured.get('loops', 1))})")
            lines.append(line)
            pad = " " * (6 * depth + 2)
            for detail in node.details:
                lines.append(pad + detail)
                if (analyze and detail.startswith("Filter:") and measured is not None
                        and node.input_key in profile and node.input_key != used_key):
                    lines.append(pad + f"Rows Removed by Filter: {profile[node.input_key]['rows'] - measured['rows']}")
            if analyze and node.is_sort and stats is not None and measured is not None:
                if stats.initial_runs > 1:
                    lines.append(pad + f"Sort Method: external merge  Runs: {stats.initial_runs}  "
                                       f"Merge passes: {stats.merge_passes}")
                else:
                    lines.append(pad + "Sort Method: in-memory (1 run)")
            for child in node.children:
                emit(child, depth + 1)

        emit(root, 0)
        return lines
