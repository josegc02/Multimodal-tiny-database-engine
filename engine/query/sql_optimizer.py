"""Adapta el árbol SQL al planificador físico por costos de páginas."""

import math

from engine.query import ast
from engine.query.external_algorithms import OrderKey
from engine.query.planner import QueryPlanner, TableStats


def base_scan(plan):
    while plan.operation == "Filter":
        plan = plan.children[0]
    return plan if plan.operation == "Scan" else None


class SQLOptimizer:
    def __init__(self, catalog, config):
        self.catalog = catalog
        self.costs = QueryPlanner(config)

    def estimates(self, plan):
        if plan.operation == "Scan":
            return self.catalog.table(plan.get("table").name).statistics
        left = self.estimates(plan.children[0])
        if plan.operation == "Join":
            right = self.estimates(plan.children[1])
            rows = left.rows * right.rows  # Cota conservadora para joins encadenados.
            return TableStats(rows, math.ceil(rows / self.costs.config.records_per_page))
        return left

    @staticmethod
    def _constant(expression):
        """(True, valor) si la expresión es un literal (incluido -literal)."""
        if isinstance(expression, ast.Literal) and type(expression.value) in (int, float, str):
            return True, expression.value
        if (isinstance(expression, ast.UnaryOp) and expression.operator in ("-", "+")
                and isinstance(expression.operand, ast.Literal)
                and type(expression.operand.value) in (int, float)):
            value = expression.operand.value
            return True, -value if expression.operator == "-" else value
        return False, None

    @classmethod
    def _conjuncts(cls, expression):
        if isinstance(expression, ast.BinaryOp) and expression.operator == "AND":
            yield from cls._conjuncts(expression.left)
            yield from cls._conjuncts(expression.right)
        elif expression is not None:
            yield expression

    def _equalities(self, expression, qualifier):
        for term in self._conjuncts(expression):
            if isinstance(term, ast.BinaryOp) and term.operator == "=":
                for col, value in ((term.left, term.right), (term.right, term.left)):
                    is_constant, constant = self._constant(value)
                    if isinstance(col, ast.ColumnRef) and col.table == qualifier and is_constant:
                        yield col.name, constant

    _FLIP = {"<": ">", "<=": ">=", ">": "<", ">=": "<="}

    def _ranges(self, expression, qualifier):
        """{columna: (lower, upper, include_lower, include_upper)} de los conjuntos AND."""
        ranges = {}

        def tighten(name, lower=None, upper=None, include_lower=True, include_upper=True):
            low, high, inc_low, inc_high = ranges.get(name, (None, None, True, True))
            try:
                if lower is not None and (low is None or lower > low or (lower == low and not include_lower)):
                    low, inc_low = lower, include_lower
                if upper is not None and (high is None or upper < high or (upper == high and not include_upper)):
                    high, inc_high = upper, include_upper
            except TypeError:  # límites de tipos incomparables: no se usa índice
                return
            ranges[name] = (low, high, inc_low, inc_high)

        for term in self._conjuncts(expression):
            if isinstance(term, ast.Between) and not term.negated:
                column = term.expression
                ok_low, low = self._constant(term.lower)
                ok_high, high = self._constant(term.upper)
                if isinstance(column, ast.ColumnRef) and column.table == qualifier and ok_low and ok_high:
                    tighten(column.name, low, high)
            elif isinstance(term, ast.BinaryOp) and term.operator in self._FLIP:
                operator, column, value = term.operator, term.left, term.right
                if not isinstance(column, ast.ColumnRef):
                    operator, column, value = self._FLIP[operator], term.right, term.left
                is_constant, constant = self._constant(value)
                if not (isinstance(column, ast.ColumnRef) and column.table == qualifier and is_constant):
                    continue
                if operator in ("<", "<="):
                    tighten(column.name, upper=constant, include_upper=operator == "<=")
                else:
                    tighten(column.name, lower=constant, include_lower=operator == ">=")
        return ranges

    @staticmethod
    def _compatible(kind, value):
        """El valor puede compararse con las claves del índice sin convertir tipos."""
        if value is None:
            return True
        if kind == "int":
            return type(value) is int
        if kind == "float":
            return type(value) in (int, float)
        return type(value) is str

    def choice(self, plan):
        if plan.operation == "Scan":
            table = plan.get("table")
            binding = self.catalog.table(table.name)
            qualifier = table.alias or table.name
            predicate = plan.get("predicate")
            indexes = binding.index_info()
            schema = binding.storage.schema
            kinds = dict(zip(schema.fields, schema.types))
            candidates = [self.costs.plan_equality(binding.statistics, field, value, indexes)
                          for field, value in self._equalities(predicate, qualifier)]
            for field, (lower, upper, include_lower, include_upper) in self._ranges(predicate, qualifier).items():
                if self._compatible(kinds[field], lower) and self._compatible(kinds[field], upper):
                    candidates.append(self.costs.plan_range(binding.statistics, field, lower, upper,
                                                            include_lower, include_upper, indexes))
            return min(candidates, key=lambda p: p.estimated_io) if candidates else self.costs._plan(
                "scan", "sequential_scan", binding.statistics.pages,
                "No hay un predicado de igualdad o rango utilizable por un índice.")
        if plan.operation == "Join":
            right = plan.children[1]
            binding = self.catalog.table(right.get("table").name)
            pairs = plan.get("pairs")
            return self.costs.plan_join(self.estimates(plan.children[0]), binding.statistics,
                                        tuple(l.name for l, _ in pairs), tuple(r.name for _, r in pairs),
                                        binding.index_info())
        if plan.operation not in ("Sort", "Aggregate"):
            return None
        source = plan.children[0]
        scan = base_scan(source)
        binding = self.catalog.table(scan.get("table").name) if scan else None
        if plan.operation == "Sort":
            items = plan.get("order_by")
            simple = scan is not None and all(isinstance(i.expression, ast.ColumnRef) for i in items)
            keys = tuple(OrderKey(i.expression.name if simple else f"$sort{n}", i.direction == "DESC",
                                  i.nulls_first if i.nulls_first is not None else i.direction == "DESC")
                         for n, i in enumerate(items))
            return self.costs.plan_order_by(self.estimates(source), keys,
                                            binding.index_info() if simple else ())
        groups = plan.get("group_by")
        simple = scan is not None and all(isinstance(g, ast.ColumnRef) for g in groups)
        fields = tuple(g.name if simple else f"$group{n}" for n, g in enumerate(groups))
        return self.costs.plan_group_by(self.estimates(source), fields,
                                        indexes=binding.index_info() if simple else ())

    def explain(self, plan):
        result = plan.to_dict()
        if plan.operation == "Scan":
            table = plan.get("table")
            if table is not None:
                storage = self.catalog.table(table.name).storage
                result["storage"] = type(storage).__name__
        choice = self.choice(plan)
        if choice is not None:
            result["physical"] = choice.explain()
        result["children"] = [self.explain(child) for child in plan.children]
        # Un recorrido ordenado sustituye al acceso original del subárbol.
        if choice is not None and choice.algorithm in ("index_order_scan", "index_group_by"):
            child = result["children"][0]
            while child["operation"] == "Filter":
                child = child["children"][0]
            child["physical"] = choice.explain()
        if choice is not None and choice.algorithm == "index_nested_loop_join":
            result["children"][1]["physical"] = {
                "algorithm": "index_lookup_per_left_row", "index": choice.index.name,
                "reason": "El join sondea este índice por cada fila izquierda; costo incluido en el join.",
            }
        return result
