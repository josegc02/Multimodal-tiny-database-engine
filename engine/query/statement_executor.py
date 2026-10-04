"""Ejecucion de sentencias AST con soporte de transacciones.

Coordina:
- TransactionManager (para BEGIN / COMMIT / ROLLBACK)
- LockManager (locks de tabla y de fila, 2PL estricto)
- Catalog (storage e índices de cada tabla)
- SQLExecutor (planes de SELECT y DELETE)

Protocolo de locks (granularidad múltiple):
- SELECT: S sobre cada tabla leída. Bloquea mientras otra transacción tenga
  escrituras sin confirmar (IX/SIX/X), así que no hay lecturas sucias.
- INSERT: IX sobre la tabla y X sobre cada fila (por su clave). Inserciones
  de claves distintas pueden ejecutarse en paralelo.
- DELETE: SIX sobre la tabla (lee la tabla para evaluar su WHERE, así que no
  puede ver borrados o inserciones sin confirmar de otros) y X sobre cada fila.
- Leer y luego escribir en la misma transacción convierte S en SIX. Si dos
  transacciones lo hacen a la vez se produce un deadlock: el LockManager lo
  detecta, la transacción que cierra el ciclo se aborta (rollback) y la otra
  continúa sin perder la actualización. El cliente reintenta la abortada.
- Los locks se mantienen hasta COMMIT/ROLLBACK (en autocommit, hasta el final
  de la sentencia).

Regla de orden: primero se obtiene el lock lógico y después el latch físico de
la tabla, que es corto. Nunca se espera un lock reteniendo un latch.
"""

from __future__ import annotations

import csv
import os
import time
from typing import Optional

from engine.concurrency.lock_manager import DeadlockError, LockMode
from engine.query.ast import (CopyStatement, DeleteStatement, ExplainStatement, InsertStatement,
                              Literal, SelectStatement, TransactionStatement)
from engine.query.errors import SQLExecutionError, SQLIntegrityError, SQLSemanticError
from engine.query.external_algorithms import ExecutionStats
from engine.query.logical_plan import LogicalPlan, LogicalPlanner, normalize_insert


def _scanned_tables(plan: LogicalPlan):
    """Nombres de las tablas que lee un plan lógico."""
    tables = set()
    pending = [plan]
    while pending:
        node = pending.pop()
        if node.operation == "Scan" and node.get("table") is not None:
            tables.add(node.get("table").name)
        pending.extend(node.children)
    return tables


class StatementExecutor:
    """Ejecuta sentencias AST de una sesión.

    Mantiene el estado de la sesion (current_tx_id). Cada hilo o usuario debe
    tener su propio StatementExecutor; el TransactionManager, el LockManager y
    el Catalog se comparten.
    """

    def __init__(self, transaction_manager, lock_manager=None, storage=None,
                 query_executor=None, planner=None, base_dir=None):
        self.tm = transaction_manager
        # Carpeta desde la que se resuelven las rutas relativas de COPY.
        self.base_dir = base_dir or os.getcwd()
        self.lock_manager = lock_manager
        self.storage = storage
        if query_executor is None and storage is not None and callable(getattr(storage, "table", None)):
            from engine.query.sql_executor import SQLExecutor
            query_executor = SQLExecutor(storage)
        self.query_executor = query_executor
        self.planner = planner or (LogicalPlanner(storage) if storage is not None else None)
        self.current_tx_id: Optional[int] = None

    @property
    def in_transaction(self) -> bool:
        return self.current_tx_id is not None

    def execute(self, statement):
        """Despacha una sentencia. SELECT devuelve la lista de filas; el resto, un mensaje.

        Si la sentencia provoca un deadlock dentro de una transacción explícita,
        la transacción completa se aborta y se relanza DeadlockError.
        """
        explicit_tx = self.current_tx_id
        try:
            return self._dispatch(statement)
        except DeadlockError as exc:
            if explicit_tx is not None and self.current_tx_id == explicit_tx:
                self._rollback()
                raise DeadlockError(
                    f"{exc}. La transacción {explicit_tx} fue abortada (rollback); vuelva a ejecutarla."
                ) from exc
            raise

    def _dispatch(self, statement):
        if isinstance(statement, TransactionStatement):
            return self._execute_transaction(statement)
        if isinstance(statement, InsertStatement):
            return self._execute_insert(statement)
        if isinstance(statement, DeleteStatement):
            return self._execute_delete(statement)
        if isinstance(statement, (SelectStatement, LogicalPlan)):
            return self.select(statement)
        if isinstance(statement, CopyStatement):
            return self._execute_copy(statement)
        if isinstance(statement, ExplainStatement):
            return self._execute_explain(statement)
        raise NotImplementedError(
            f"Sentencia no soportada: {type(statement).__name__}"
        )

    # --- BEGIN / COMMIT / ROLLBACK ---

    def _execute_transaction(self, statement: TransactionStatement):
        """Maneja BEGIN / COMMIT (END) / ROLLBACK."""
        action = statement.action

        if action == "BEGIN":
            return self._begin()
        if action == "COMMIT":
            return self._commit()
        if action == "ROLLBACK":
            return self._rollback()

        raise ValueError(f"Accion de transaccion desconocida: {action}")

    def _begin(self):
        """Inicia una nueva transaccion."""
        if self.current_tx_id is not None:
            raise RuntimeError("Ya hay una transaccion activa")
        self.current_tx_id = self.tm.begin()
        return f"Transaccion {self.current_tx_id} iniciada"

    def _commit(self):
        """Confirma la transaccion activa."""
        if self.current_tx_id is None:
            raise RuntimeError("No hay transaccion activa")
        tx_id = self.current_tx_id
        self.current_tx_id = None
        self.tm.commit(tx_id)
        return f"Transaccion {tx_id} confirmada"

    def _rollback(self):
        """Aborta la transaccion activa."""
        if self.current_tx_id is None:
            raise RuntimeError("No hay transaccion activa")
        tx_id = self.current_tx_id
        self.current_tx_id = None
        self.tm.rollback(tx_id)
        return f"Transaccion {tx_id} abortada"

    def _run_in_transaction(self, work):
        """Ejecuta work(tx) en la transacción activa o en una de autocommit."""
        if self.storage is None:
            raise RuntimeError("Storage no configurado")
        autocommit = self.current_tx_id is None
        if autocommit:
            self._begin()
        tx = self.tm.get_transaction(self.current_tx_id)
        mark = len(tx.undo_log)
        try:
            result = work(tx)
        except Exception:
            if autocommit and self.current_tx_id is not None:
                self._rollback()
            elif self.current_tx_id is not None and len(tx.undo_log) > mark:
                # La sentencia es atómica: se deshace solo lo que ella hizo.
                self.tm.rollback_to(tx.tx_id, mark)
            raise
        if autocommit:
            self._commit()
        return result

    def _lock(self, tx, resource: str, mode: LockMode) -> None:
        if self.lock_manager is not None:
            self.lock_manager.acquire(tx.tx_id, resource, mode)
            tx.add_lock(resource, mode)

    @staticmethod
    def _key_field(binding):
        """Columna que identifica una fila para los locks X (la clave primaria si existe)."""
        storage = binding.storage
        return binding.primary_key or getattr(storage, "key_field", None) or storage.schema.fields[0]

    # --- SELECT ---

    def select(self, statement, *, stats=None):
        """Ejecuta un SELECT (AST o LogicalPlan) con locks S y devuelve sus filas."""
        if self.query_executor is None:
            raise RuntimeError("No hay un ejecutor de consultas configurado")
        plan = statement if isinstance(statement, LogicalPlan) else self.planner.plan(statement)

        def work(tx):
            for table in sorted(_scanned_tables(plan)):  # orden fijo entre tablas
                self._lock(tx, table, LockMode.SHARED)
            return list(self.query_executor.execute(plan, stats=stats))

        return self._run_in_transaction(work)

    # --- INSERT ---

    def _execute_insert(self, statement: InsertStatement):
        """Ejecuta un INSERT, con o sin transaccion activa."""
        binding = self.storage.table(statement.table)
        columns = statement.columns or tuple(binding.storage.schema.fields)
        # Valida tipos y columnas de todo el lote antes de escribir.
        records = normalize_insert(binding, columns, statement.values)
        count = self._insert_records(statement.table, binding, records)
        return f"{count} registro(s) insertado(s)"

    def _insert_records(self, table, binding, records):
        """Inserta registros ya validados (INSERT y COPY) con locks, PK y undo log."""
        storage = binding.storage
        key_field = self._key_field(binding)

        def work(tx):
            self._lock(tx, table, LockMode.INTENTION_EXCLUSIVE)
            try:
                for record in records:
                    self._lock(tx, f"{table}:{record[key_field]}", LockMode.EXCLUSIVE)
                    self._check_references(tx, table, binding, record)
                    with binding.latch:
                        binding.ensure_unique(record)
                        rid = storage.insert(record)
                        stored = storage.get(rid)
                        binding.record_inserted(rid, stored)
                        tx.add_operation({
                            "op": "INSERT",
                            "table": table,
                            "rid": rid,
                            "record": stored,
                        })
            finally:
                binding.finish_write()
            return len(records)

        return self._run_in_transaction(work)

    def _check_references(self, tx, table, binding, record):
        """Cada llave foránea de `record` debe existir en su tabla padre.

        Toma un lock S sobre la fila padre: nadie puede borrarla hasta que
        termine esta transacción. Se verifica antes del latch de la tabla hija.
        """
        for foreign_key in binding.foreign_keys:
            value = record[foreign_key.column]
            parent = self.storage.table(foreign_key.ref_table)
            if foreign_key.ref_table == table and value == record[foreign_key.ref_column]:
                continue  # fila que se referencia a sí misma
            self._lock(tx, foreign_key.ref_table, LockMode.INTENTION_SHARED)
            self._lock(tx, f"{foreign_key.ref_table}:{value}", LockMode.SHARED)
            if not parent._key_exists(value):
                raise SQLIntegrityError(
                    f'inserción en la tabla "{table}" viola la llave foránea "{foreign_key.name}": '
                    f'la llave ({foreign_key.column})=({value}) no está presente en la tabla '
                    f'"{foreign_key.ref_table}"')

    # --- COPY ---

    def _execute_copy(self, statement: CopyStatement):
        """COPY tabla FROM 'archivo.csv': valida todo el archivo y lo inserta en una transacción."""
        binding = self.storage.table(statement.table)
        schema = binding.storage.schema
        columns = statement.columns or tuple(schema.fields)
        unknown = [column for column in columns if column not in schema.fields]
        if unknown:
            raise SQLSemanticError(f"La columna {unknown[0]!r} no existe en {statement.table!r}")
        kinds = dict(zip(schema.fields, schema.types))
        path = statement.path if os.path.isabs(statement.path) else os.path.join(self.base_dir, statement.path)
        if not os.path.isfile(path):
            raise SQLExecutionError(f'no se pudo abrir el archivo "{path}": no existe')

        encoding = "utf-8-sig" if statement.encoding == "utf-8" else statement.encoding
        records = []
        try:
            with open(path, newline="", encoding=encoding) as stream:
                reader = csv.reader(stream, delimiter=statement.delimiter)
                first = True
                for row in reader:
                    line = reader.line_num
                    if first and statement.header:
                        first = False
                        continue
                    first = False
                    if not row or all(not value.strip() for value in row):
                        continue  # líneas vacías
                    if len(row) != len(columns):
                        raise SQLExecutionError(
                            f"COPY {statement.table}, línea {line}: se esperaban {len(columns)} "
                            f"valores y se encontraron {len(row)}")
                    values = tuple(Literal(self._csv_value(text, kinds[column], column, statement.table, line))
                                   for column, text in zip(columns, row))
                    try:
                        records.extend(normalize_insert(binding, columns, [values]))
                    except SQLSemanticError as exc:
                        raise SQLExecutionError(f"COPY {statement.table}, línea {line}: {exc}") from None
        except UnicodeDecodeError as exc:
            raise SQLExecutionError(
                f"COPY {statement.table}: el archivo no está en {statement.encoding.upper()} ({exc.reason}); "
                "use ENCODING 'LATIN1' o 'WIN1252'") from None
        self._insert_records(statement.table, binding, records)
        return f"COPY {len(records)}"

    @staticmethod
    def _csv_value(text, kind, column, table, line):
        if kind == "str":
            return text
        value = text.strip()
        if not value:
            raise SQLExecutionError(
                f"COPY {table}, línea {line}: valor vacío en {column!r} (el storage no admite NULL)")
        try:
            return int(value) if kind == "int" else float(value)
        except ValueError:
            raise SQLExecutionError(
                f"COPY {table}, línea {line}: {value!r} no es un valor {kind.upper()} válido "
                f"para {column!r}") from None

    # --- EXPLAIN ---

    def _execute_explain(self, statement: ExplainStatement):
        """Plan con formato de PostgreSQL. ANALYZE ejecuta la sentencia y mide cada operador."""
        from engine.query.explain import PlanExplainer

        started = time.perf_counter()
        inner = statement.statement
        plan = self.planner.plan(inner)
        explainer = PlanExplainer(self.storage, self.query_executor.optimizer)
        root = explainer.build(plan)
        planning = time.perf_counter() - started
        if not statement.analyze:
            return explainer.render(root)

        stats = ExecutionStats(profile={})
        started = time.perf_counter()
        if isinstance(inner, SelectStatement):
            self.select(plan, stats=stats)
        elif isinstance(inner, DeleteStatement):
            self._execute_delete(inner, plan=plan, stats=stats)
        else:
            self._execute_insert(inner)
        execution = time.perf_counter() - started
        if not isinstance(inner, SelectStatement):
            root.actual = {"rows": 0, "first": execution, "total": execution, "loops": 1}
        return explainer.render(root, stats.profile, stats) + [
            f"Planning Time: {planning * 1000:.3f} ms",
            f"Execution Time: {execution * 1000:.3f} ms",
        ]

    # --- DELETE ---

    def _execute_delete(self, statement: DeleteStatement, *, plan=None, stats=None):
        """Ejecuta un DELETE, con o sin transaccion activa."""
        table_name = statement.table.name
        binding = self.storage.table(table_name)
        storage = binding.storage
        key_field = self._key_field(binding)
        plan = plan or self.planner.plan(statement)

        def work(tx):
            self._lock(tx, table_name, LockMode.SHARED_INTENTION_EXCLUSIVE)
            # Candidatas según el plan (usa índices si conviene); no se modifica nada aún.
            candidates = list(self.query_executor.matching_records(plan, stats=stats))
            deleted = 0
            touched = {table_name: binding}
            try:
                for rid, record in candidates:
                    self._lock(tx, f"{table_name}:{record[key_field]}", LockMode.EXCLUSIVE)
                    deleted += self._delete_row(tx, table_name, binding, rid, record, touched, set())
            finally:
                for touched_binding in touched.values():
                    touched_binding.finish_write()
            return f"{deleted} registro(s) eliminado(s)"

        return self._run_in_transaction(work)

    def _delete_row(self, tx, table, binding, rid, record, touched, visiting):
        """Elimina una fila aplicando las llaves foráneas que la referencian.

        RESTRICT: falla si hay filas hijas. CASCADE: elimina primero las hijas
        (recursivamente), así un ROLLBACK restaura el padre antes que sus hijas.
        Devuelve 1 si la fila existía y se eliminó.
        """
        # Solo una fila con clave primaria puede ser referenciada y, por lo tanto,
        # formar un ciclo (p. ej. una fila que se referencia a sí misma).
        if binding.primary_key is not None:
            identity = (table, record[binding.primary_key])
            if identity in visiting:
                return 0
            visiting.add(identity)
        for foreign_key in self.storage.referencing(table):
            child = self.storage.table(foreign_key.table)
            children = [(child_rid, child_record)
                        for child_rid, child_record in child.rows_with(foreign_key.column,
                                                                      record[foreign_key.ref_column])
                        if not (foreign_key.table == table and child_record == record)]
            if not children:
                continue
            if foreign_key.on_delete != "CASCADE":
                raise SQLIntegrityError(
                    f'eliminar en la tabla "{table}" viola la llave foránea "{foreign_key.name}" '
                    f'de la tabla "{foreign_key.table}": la llave ({foreign_key.ref_column})='
                    f'({record[foreign_key.ref_column]}) todavía es referida desde la tabla '
                    f'"{foreign_key.table}"')
            self._lock(tx, foreign_key.table, LockMode.SHARED_INTENTION_EXCLUSIVE)
            touched.setdefault(foreign_key.table, child)
            child_key = self._key_field(child)
            for child_rid, child_record in children:
                self._lock(tx, f"{foreign_key.table}:{child_record[child_key]}", LockMode.EXCLUSIVE)
                self._delete_row(tx, foreign_key.table, child, child_rid, child_record, touched, visiting)
        with binding.latch:
            # Otra transacción pudo moverla o eliminarla mientras se esperaba el lock.
            current = binding.locate(rid, record)
            if current is None or not binding.storage.delete(current):
                return 0
            binding.record_deleted(current, record)
            tx.add_operation({"op": "DELETE", "table": table, "rid": current, "old": record})
        return 1
