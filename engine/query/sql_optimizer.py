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

    def _equalities(self, expression, qualifier):
        if isinstance(expression, ast.BinaryOp):
            if expression.operator == "AND":
                yield from self._equalities(expression.left, qualifier)
                yield from self._equalities(expression.right, qualifier)
            elif expression.operator == "=":
                for col, value in ((expression.left, expression.right), (expression.right, expression.left)):
                    if (isinstance(col, ast.ColumnRef) and col.table == qualifier
                            and isinstance(value, ast.Literal) and type(value.value) in (int, float, str)):
                        yield col.name, value.value

    def choice(self, plan):
        if plan.operation == "Scan":
            table = plan.get("table")
            binding = self.catalog.table(table.name)
            candidates = [self.costs.plan_equality(binding.statistics, field, value, binding.index_info())
                          for field, value in self._equalities(plan.get("predicate"), table.alias or table.name)]
            return min(candidates, key=lambda p: p.estimated_io) if candidates else self.costs._plan(
                "scan", "sequential_scan", binding.statistics.pages,
                "No hay un predicado de igualdad utilizable por un índice.")
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
