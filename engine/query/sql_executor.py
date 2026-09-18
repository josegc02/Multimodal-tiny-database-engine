"""Ejecución de planes lógicos contra storages registrados e índices de igualdad."""

from contextlib import closing
from itertools import islice
import tempfile

from engine.query import ast
from engine.query._temp_records import read_header, read_record, write_header, write_record
from engine.query.catalog import Catalog
from engine.query.expressions import evaluate, truth
from engine.query.external_algorithms import (
    Aggregate, BufferConfig, ExecutionStats, OrderKey,
    external_hash_group_by, external_hash_join, external_sort,
)
from engine.query.logical_plan import LogicalPlan, LogicalPlanner, column_key, normalize_insert
from engine.query.errors import SQLExecutionError
from engine.query.parser import parse
from engine.storage.record import RID


def _rid_keys(qualifier):
    prefix = f"@{len(qualifier)}:{qualifier}:"
    return tuple(prefix + name for name in ("page", "slot", "file"))


def _context(table, rid, record):
    qualifier = table.alias or table.name
    row = {column_key(ast.ColumnRef(name, qualifier)): value for name, value in record.items()}
    row.update(zip(_rid_keys(qualifier), (rid.page_id, rid.slot_id, rid.file)))
    return row


def _computed(rows, expressions, prefix):
    for row in rows:
        yield {**row, **{f"{prefix}{i}": evaluate(expr, row) for i, expr in enumerate(expressions)}}


class SQLExecutor:
    """SELECT es incremental; INSERT y DELETE se aplican al llamar execute().

    Las mutaciones devuelven un iterable con {'affected_rows': n}. Se validan
    antes de escribir, pero no hay rollback ante fallos de I/O. En ese caso los
    índices quedan inválidos y las consultas usan scan hasta reconstruirlos.
    Cerrar el iterador SELECT cuando no se consuma por completo.
    """

    def __init__(self, catalog: Catalog, config: BufferConfig | None = None):
        self.catalog = catalog
        self.config = config or BufferConfig()
        self.planner = LogicalPlanner(catalog)

    def explain(self, sql):
        return self.planner.plan(parse(sql)).to_dict()

    def execute(self, sql_or_plan, *, stats: ExecutionStats | None = None):
        plan = self.planner.plan(parse(sql_or_plan)) if isinstance(sql_or_plan, str) else sql_or_plan
        if not isinstance(plan, LogicalPlan):
            raise TypeError("Se requiere SQL o un LogicalPlan")
        stats = stats if stats is not None else ExecutionStats()
        if plan.operation == "Insert":
            return iter(({"affected_rows": self._insert(plan)},))
        if plan.operation == "Delete":
            return iter(({"affected_rows": self._delete(plan, stats)},))
        return self._run(plan, stats)

    def _lookup(self, expression, qualifier, binding):
        if isinstance(expression, ast.BinaryOp) and expression.operator == "AND":
            return self._lookup(expression.left, qualifier, binding) or self._lookup(expression.right, qualifier, binding)
        if isinstance(expression, ast.BinaryOp) and expression.operator == "=":
            for column, literal in ((expression.left, expression.right), (expression.right, expression.left)):
                if (isinstance(column, ast.ColumnRef) and column.table == qualifier
                        and isinstance(literal, ast.Literal) and type(literal.value) in (int, float, str)):
                    index = binding.indexes.get(column.name)
                    if index is not None and index.valid:
                        return index.index, literal.value
        return None

    def _scan(self, plan, stats):
        table = plan.get("table")
        binding = self.catalog.table(table.name)
        lookup = self._lookup(plan.get("predicate"), table.alias or table.name, binding)
        if lookup is None:
            for rid, record in binding.storage.scan():
                yield _context(table, rid, record)
        else:
            index, value = lookup
            stats.index_probes += 1
            for rid in index.search(value):
                record = binding.storage.get(rid)
                if record is not None:
                    yield _context(table, rid, record)

    def _run(self, plan, stats):
        operation = plan.operation
        if operation == "Scan":
            yield from self._scan(plan, stats)
            return
        with closing(self._run(plan.children[0], stats)) as rows:
            if operation == "Filter":
                for row in rows:
                    if truth(evaluate(plan.get("predicate"), row)) is True:
                        yield row
            elif operation == "Project":
                for row in rows:
                    yield {label: evaluate(expression, row) for label, expression in plan.get("columns")}
            elif operation == "Limit":
                offset, limit = plan.get("offset"), plan.get("limit")
                yield from islice(rows, offset, None if limit is None else offset + limit)
            elif operation == "Sort":
                order = plan.get("order_by")
                keyed = _computed(rows, tuple(item.expression for item in order), "$sort")
                keys = [OrderKey(f"$sort{i}", item.direction == "DESC",
                                 item.nulls_first if item.nulls_first is not None else item.direction == "DESC")
                        for i, item in enumerate(order)]
                yield from external_sort(keyed, keys, config=self.config, stats=stats)
            elif operation == "Aggregate":
                groups, aggregates = plan.get("group_by"), plan.get("aggregates")
                def prepared():
                    for row in rows:
                        result = {f"$group{i}": evaluate(expr, row) for i, expr in enumerate(groups)}
                        for i, aggregate in enumerate(aggregates):
                            if not isinstance(aggregate.argument, ast.Star):
                                result[f"$value{i}"] = evaluate(aggregate.argument, row)
                        yield result
                specs = {f"$agg{i}": Aggregate(call.function, None if isinstance(call.argument, ast.Star) else f"$value{i}")
                         for i, call in enumerate(aggregates)}
                yield from external_hash_group_by(prepared(), tuple(f"$group{i}" for i in range(len(groups))),
                                                  specs or {"$unused": Aggregate()}, config=self.config, stats=stats)
            elif operation == "Distinct":
                expressions = plan.get("expressions")
                keys = tuple(f"$distinct{i}" for i in range(len(expressions)))
                previous = object()
                with closing(external_sort(_computed(rows, expressions, "$distinct"), keys,
                                           config=self.config, stats=stats)) as ordered:
                    for row in ordered:
                        key = tuple(row[name] for name in keys)
                        if key != previous:
                            yield row
                            previous = key
            elif operation == "Join":
                pairs = plan.get("pairs")
                with closing(self._run(plan.children[1], stats)) as right:
                    with closing(external_hash_join(rows, right, tuple(column_key(l) for l, _ in pairs),
                                                    tuple(column_key(r) for _, r in pairs),
                                                    config=self.config, stats=stats)) as joined:
                        for left_row, right_row in joined:
                            row = {**left_row, **right_row}
                            if truth(evaluate(plan.get("predicate"), row)) is True:
                                yield row
            else:
                raise SQLExecutionError(f"Operador lógico no soportado: {operation}")

    def _insert(self, plan):
        binding = self.catalog.table(plan.get("table"))
        records = normalize_insert(binding, plan.get("columns"), plan.get("values"))
        binding.invalidate_indexes()
        for record in records:
            binding.storage.insert(record)
        binding.refresh_indexes()
        return len(records)

    def _delete(self, plan, stats):
        table = plan.get("table")
        binding = self.catalog.table(table.name)
        rid_keys = _rid_keys(table.alias or table.name)
        # Primero evaluar todos los filtros. Si alguno falla no se elimina nada.
        # Guardar RIDs en disco evita retener todos los registros seleccionados.
        with tempfile.TemporaryFile(dir=self.config.temp_dir) as fh:
            write_header(fh)
            count = 0
            with closing(self._run(plan.children[0], stats)) as rows:
                for row in rows:
                    write_record(fh, dict(zip(("page", "slot", "file"), (row[key] for key in rid_keys))))
                    count += 1
            fh.seek(0)
            read_header(fh)
            binding.invalidate_indexes()
            deleted = 0
            for _ in range(count):
                rid = read_record(fh)
                deleted += bool(binding.storage.delete(RID(rid["page"], rid["slot"], rid["file"])))
        binding.refresh_indexes()
        return deleted
