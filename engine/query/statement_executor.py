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

from typing import Optional

from engine.concurrency.lock_manager import DeadlockError, LockMode
from engine.query.ast import (DeleteStatement, InsertStatement, SelectStatement,
                              TransactionStatement)
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
                 query_executor=None, planner=None):
        self.tm = transaction_manager
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
        try:
            result = work(tx)
        except Exception:
            if autocommit and self.current_tx_id is not None:
                self._rollback()
            raise
        if autocommit:
            self._commit()
        return result

    def _lock(self, tx, resource: str, mode: LockMode) -> None:
        if self.lock_manager is not None:
            self.lock_manager.acquire(tx.tx_id, resource, mode)
            tx.add_lock(resource, mode)

    @staticmethod
    def _key_field(storage):
        return getattr(storage, "key_field", None) or storage.schema.fields[0]

    # --- SELECT ---

    def select(self, statement):
        """Ejecuta un SELECT (AST o LogicalPlan) con locks S y devuelve sus filas."""
        if self.query_executor is None:
            raise RuntimeError("No hay un ejecutor de consultas configurado")
        plan = statement if isinstance(statement, LogicalPlan) else self.planner.plan(statement)

        def work(tx):
            for table in sorted(_scanned_tables(plan)):  # orden fijo entre tablas
                self._lock(tx, table, LockMode.SHARED)
            return list(self.query_executor.execute(plan))

        return self._run_in_transaction(work)

    # --- INSERT ---

    def _execute_insert(self, statement: InsertStatement):
        """Ejecuta un INSERT, con o sin transaccion activa."""
        binding = self.storage.table(statement.table)
        storage = binding.storage
        columns = statement.columns or tuple(storage.schema.fields)
        # Valida tipos y columnas de todo el lote antes de escribir.
        records = normalize_insert(binding, columns, statement.values)
        key_field = self._key_field(storage)

        def work(tx):
            self._lock(tx, statement.table, LockMode.INTENTION_EXCLUSIVE)
            try:
                for record in records:
                    self._lock(tx, f"{statement.table}:{record[key_field]}", LockMode.EXCLUSIVE)
                    with binding.latch:
                        binding.invalidate_indexes()
                        rid = storage.insert(record)
                        tx.add_operation({
                            "op": "INSERT",
                            "table": statement.table,
                            "rid": rid,
                            "record": storage.get(rid),
                        })
            finally:
                binding.refresh_indexes()
            return f"{len(records)} registro(s) insertado(s)"

        return self._run_in_transaction(work)

    # --- DELETE ---

    def _execute_delete(self, statement: DeleteStatement):
        """Ejecuta un DELETE, con o sin transaccion activa."""
        table_name = statement.table.name
        binding = self.storage.table(table_name)
        storage = binding.storage
        key_field = self._key_field(storage)
        plan = self.planner.plan(statement)

        def work(tx):
            self._lock(tx, table_name, LockMode.SHARED_INTENTION_EXCLUSIVE)
            # Candidatas según el plan (usa índices si conviene); no se modifica nada aún.
            candidates = list(self.query_executor.matching_records(plan))
            deleted = 0
            try:
                for rid, record in candidates:
                    self._lock(tx, f"{table_name}:{record[key_field]}", LockMode.EXCLUSIVE)
                    with binding.latch:
                        # Otra transacción pudo moverla o eliminarla mientras se esperaba el lock.
                        current = binding.locate(rid, record)
                        if current is None:
                            continue
                        binding.invalidate_indexes()
                        if storage.delete(current):
                            tx.add_operation({
                                "op": "DELETE",
                                "table": table_name,
                                "rid": current,
                                "old": record,
                            })
                            deleted += 1
            finally:
                binding.refresh_indexes()
            return f"{deleted} registro(s) eliminado(s)"

        return self._run_in_transaction(work)
