"""Ejecución de planes lógicos contra storages registrados e índices de igualdad."""

from contextlib import closing
from itertools import islice
import tempfile
import time

from engine.query import ast
from engine.query._temp_records import read_header, read_record, write_header, write_record
from engine.query.catalog import Catalog
from engine.query.expressions import evaluate, truth
from engine.query.external_algorithms import (
    Aggregate, BufferConfig, ExecutionStats, OrderKey,
    external_hash_group_by, external_hash_join, external_sort, streaming_group_by,
)
from engine.query.logical_plan import LogicalPlan, LogicalPlanner, column_key, normalize_insert
from engine.query.errors import SQLExecutionError
from engine.query.parser import parse
from engine.query.sql_optimizer import SQLOptimizer, base_scan
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
        self.optimizer = SQLOptimizer(catalog, self.config)

    def explain(self, sql):
        return self.optimizer.explain(self.planner.plan(parse(sql)))

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

    def matching_records(self, plan, *, stats: ExecutionStats | None = None):
        """(RID, registro) de las filas que un plan DELETE eliminaría, sin modificar nada.

        Usa el mismo plan físico que el SELECT equivalente (índices incluidos).
        """
        if not isinstance(plan, LogicalPlan) or plan.operation != "Delete":
            raise TypeError("Se requiere el LogicalPlan de un DELETE")
        table = plan.get("table")
        qualifier = table.alias or table.name
        fields = self.catalog.table(table.name).storage.schema.fields
        rid_keys = _rid_keys(qualifier)
        columns = [(name, column_key(ast.ColumnRef(name, qualifier))) for name in fields]
        with closing(self._run(plan.children[0], stats or ExecutionStats())) as rows:
            for row in rows:
                yield (RID(*(row[key] for key in rid_keys)),
                       {name: row[key] for name, key in columns})

    def _scan(self, plan, stats):
        table = plan.get("table")
        binding = self.catalog.table(table.name)
        physical = self.optimizer.choice(plan)
        if physical is None or physical.algorithm == "sequential_scan":
            for rid, record in binding.storage.scan():
                yield _context(table, rid, record)
        elif physical.algorithm == "index_range_scan":
            stats.index_probes += 1
            lower, upper, include_lower, include_upper = physical.value
            index = physical.index.index
            for rid, record in self._probe(binding, lambda: index.range_search(
                    lower, upper, include_lower=include_lower, include_upper=include_upper)):
                yield _context(table, rid, record)
        else:
            stats.index_probes += 1
            index = physical.index.index
            for rid, record in self._probe(binding, lambda: index.search(physical.value)):
                yield _context(table, rid, record)

    @staticmethod
    def _probe(binding, find_rids):
        """Búsqueda por índice + lectura de registros bajo el latch de la tabla.

        Se materializa dentro del latch para no leer un índice que otro hilo
        está reconstruyendo; los resultados se entregan fuera de él.
        """
        with binding.latch:
            found = [(rid, binding.storage.get(rid)) for rid in find_rids()]
        return [(rid, record) for rid, record in found if record is not None]

    def _ordered_source(self, source, physical):
        scan = base_scan(source)
        table = scan.get("table")
        binding = self.catalog.table(table.name)
        predicates = []
        while source.operation == "Filter":
            predicates.append(source.get("predicate"))
            source = source.children[0]
        with binding.latch:
            rids = list(physical.index.index.iter_ordered(reverse=physical.reverse))
        for rid in rids:
            record = binding.storage.get(rid)
            if record is not None:
                row = _context(table, rid, record)
                if all(truth(evaluate(predicate, row)) is True for predicate in predicates):
                    yield row

    def _run(self, plan, stats):
        if stats.profile is None:
            yield from self._run_node(plan, stats)
        else:
            yield from self._timed(plan, self._run_node(plan, stats), stats)

    @staticmethod
    def _timed(node, rows, stats):
        """Cuenta filas y tiempo (inclusivo, como PostgreSQL) de un operador."""
        entry = stats.profile.setdefault(id(node), {"rows": 0, "first": None, "total": 0.0, "loops": 0})
        entry["loops"] += 1
        iterator = iter(rows)
        try:
            while True:
                start = time.perf_counter()
                try:
                    row = next(iterator)
                except StopIteration:
                    entry["total"] += time.perf_counter() - start
                    return
                entry["total"] += time.perf_counter() - start
                if entry["first"] is None:
                    entry["first"] = entry["total"]
                entry["rows"] += 1
                yield row
        finally:
            close = getattr(iterator, "close", None)
            if close is not None:
                close()

    def _run_node(self, plan, stats):
        operation = plan.operation
        if operation == "Scan":
            yield from self._scan(plan, stats)
            return
        physical = self.optimizer.choice(plan)
        ordered = physical is not None and physical.algorithm in ("index_order_scan", "index_group_by")
        if ordered:
            source = self._ordered_source(plan.children[0], physical)
            if stats.profile is not None:
                # El recorrido del índice reemplaza al subárbol: se mide como su Scan.
                source = self._timed(base_scan(plan.children[0]), source, stats)
        else:
            source = self._run(plan.children[0], stats)
        with closing(source) as rows:
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
                if ordered:
                    yield from rows
                    return
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
                fields = tuple(f"$group{i}" for i in range(len(groups)))
                specs = specs or {"$unused": Aggregate()}
                if any(call.distinct for call in aggregates):
                    yield from self._distinct_aggregates(prepared(), fields, aggregates, specs, stats)
                elif ordered:
                    yield from streaming_group_by(prepared(), fields, specs)
                else:
                    yield from external_hash_group_by(prepared(), fields, specs, config=self.config, stats=stats)
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
                if physical.algorithm == "index_nested_loop_join":
                    table = plan.children[1].get("table")
                    binding = self.catalog.table(table.name)
                    for left_row in rows:
                        value = evaluate(pairs[0][0], left_row)
                        if value is None:
                            continue
                        stats.index_probes += 1
                        index = physical.index.index
                        for rid, record in self._probe(binding, lambda: index.search(value)):
                            row = {**left_row, **_context(table, rid, record)}
                            if truth(evaluate(plan.get("predicate"), row)) is True:
                                yield row
                    return
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

    def _distinct_aggregates(self, rows, fields, aggregates, specs, stats):
        """GROUP BY con agregados DISTINCT (p. ej. COUNT(DISTINCT x)).

        Las filas se guardan en un archivo temporal para recorrerlas varias
        veces con memoria acotada: una pasada calcula los agregados normales y,
        por cada agregado DISTINCT, otra elimina duplicados (grupo, valor) con
        hash externo y luego agrega por grupo.
        """
        def group_by(source, keys, aggregate_specs):
            return external_hash_group_by(source, keys, aggregate_specs, config=self.config, stats=stats)

        with tempfile.TemporaryFile(dir=self.config.temp_dir) as fh:
            write_header(fh)
            count = 0
            for row in rows:
                write_record(fh, row)
                count += 1

            def replay():
                fh.seek(0)
                read_header(fh)
                for _ in range(count):
                    yield read_record(fh)

            distinct = {f"$agg{i}" for i, call in enumerate(aggregates) if call.distinct}
            plain = {name: spec for name, spec in specs.items() if name not in distinct}
            results = {tuple(row[f] for f in fields): row
                       for row in group_by(replay(), fields, plain or {"$unused": Aggregate()})}
            for name in sorted(distinct):
                value = specs[name].field
                unique = group_by(replay(), fields + (value,), {"$unused": Aggregate()})
                for row in group_by(unique, fields, {name: specs[name]}):
                    results[tuple(row[f] for f in fields)][name] = row[name]
        yield from results.values()

    def _insert(self, plan):
        binding = self.catalog.table(plan.get("table"))
        records = normalize_insert(binding, plan.get("columns"), plan.get("values"))
        with binding.latch:
            try:
                for record in records:
                    binding.ensure_unique(record)
                    rid = binding.storage.insert(record)
                    binding.record_inserted(rid, binding.storage.get(rid))
            finally:
                binding.finish_write()
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
            with binding.latch:
                deleted = 0
                try:
                    for _ in range(count):
                        rid = read_record(fh)
                        rid = RID(rid["page"], rid["slot"], rid["file"])
                        record = binding.storage.get(rid)
                        if record is not None and binding.storage.delete(rid):
                            binding.record_deleted(rid, record)
                            deleted += 1
                finally:
                    binding.finish_write()
        return deleted
