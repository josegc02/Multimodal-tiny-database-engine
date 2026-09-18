"""Ejecucion de sentencias AST con soporte de transacciones.

Coordina:
- TransactionManager (para BEGIN / COMMIT / ROLLBACK)
- LockManager (para locks)
- Storage (para INSERT / DELETE)
- QueryExecutor (para SELECT)
"""

from __future__ import annotations

from typing import Optional

from engine.concurrency.lock_manager import LockMode
from engine.query import ast
from engine.query.ast import DeleteStatement, InsertStatement, TransactionStatement
from engine.query.expressions import evaluate, truth
from engine.query.logical_plan import column_key

class StatementExecutor:
    """Ejecuta sentencias AST.

    Mantiene el estado de la sesion (current_tx_id) y despacha
    cada sentencia al handler correspondiente.
    """

    def __init__(self, transaction_manager, lock_manager=None, storage=None,
                 query_executor=None, planner=None):
        self.tm = transaction_manager
        self.lock_manager = lock_manager
        self.storage = storage
        self.query_executor = query_executor
        self.planner = planner
        self.current_tx_id: Optional[int] = None

    def execute(self, statement):
        """Despacha una sentencia AST al handler correspondiente."""
        if isinstance(statement, TransactionStatement):
            return self._execute_transaction(statement)
        if isinstance(statement, InsertStatement):
            return self._execute_insert(statement)
        if isinstance(statement, DeleteStatement):
            return self._execute_delete(statement)

        raise NotImplementedError(
            f"Sentencia no soportada: {type(statement).__name__}"
        )

    def _execute_transaction(self, statement: TransactionStatement):
        """Maneja BEGIN / COMMIT / ROLLBACK."""
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
        self.tm.commit(tx_id)
        self.current_tx_id = None
        return f"Transaccion {tx_id} confirmada"

    def _rollback(self):
        """Aborta la transaccion activa."""
        if self.current_tx_id is None:
            raise RuntimeError("No hay transaccion activa")
        tx_id = self.current_tx_id
        self.tm.rollback(tx_id)
        self.current_tx_id = None
        return f"Transaccion {tx_id} abortada"


    def _execute_insert(self, statement: InsertStatement):
        """Ejecuta un INSERT, con o sin transaccion activa."""
        if self.storage is None:
            raise RuntimeError("Storage no configurado")

        # Modo autocommit si no hay transaccion activa
        autocommit = self.current_tx_id is None
        if autocommit:
            self._begin()

        tx_id = self.current_tx_id
        tx = self.tm.get_transaction(tx_id)

        try:
            # 1. Obtener la tabla
            binding = self.storage.table(statement.table)
            storage = binding.storage

            # 2. Invalidar indices (se reconstruyen al final)
            binding.invalidate_indexes()

            # 3. Construir el registro
            column_names = statement.columns
            if column_names is None:
                column_names = tuple(storage.schema.fields)

            inserted = 0
            for values in statement.values:
                # Extraer el valor de la primera columna como id
                record = dict(zip(column_names, (v.value for v in values)))
                key_value = record.get(storage.schema.fields[0])

                # 4. Pedir lock exclusivo
                if self.lock_manager is not None:
                    resource = f"{statement.table}:{key_value}"
                    self.lock_manager.acquire(tx_id, resource, LockMode.EXCLUSIVE)
                    tx.add_lock(resource, LockMode.EXCLUSIVE)

                # 5. Insertar en storage
                rid = storage.insert(record)

                # 6. Registrar en undo_log
                tx.add_operation({
                    "op": "INSERT",
                    "table": statement.table,
                    "rid": rid,
                })

                inserted += 1

            # 7. Refrescar indices
            binding.refresh_indexes()

            # 8. Commit automatico si no habia transaccion
            if autocommit:
                self._commit()

            return f"{inserted} registro(s) insertado(s)"

        except Exception:
            if autocommit:
                self._rollback()
            raise

    # --- DELETE ---

    def _execute_delete(self, statement: DeleteStatement):
        """Ejecuta un DELETE, con o sin transaccion activa."""
        if self.storage is None:
            raise RuntimeError("Storage no configurado")

        table_name = statement.table.name
        binding = self.storage.table(table_name)
        storage = binding.storage

        # 1. Recolectar RIDs que cumplen el WHERE
        to_delete = []
        for rid, record in storage.scan():
            if self._matches_where(record, statement.where):
                to_delete.append((rid, record))

        # 2. Autocommit si no hay transaccion
        autocommit = self.current_tx_id is None
        if autocommit:
            self._begin()

        tx_id = self.current_tx_id
        tx = self.tm.get_transaction(tx_id)

        try:
            binding.invalidate_indexes()

            deleted = 0
            for rid, old_record in to_delete:
                # 3. Pedir lock exclusivo sobre el registro
                key = old_record[storage.schema.fields[0]]
                resource = f"{table_name}:{key}"

                if self.lock_manager is not None:
                    self.lock_manager.acquire(tx_id, resource, LockMode.EXCLUSIVE)
                    tx.add_lock(resource, LockMode.EXCLUSIVE)

                # 4. Borrar
                if storage.delete(rid):
                    tx.add_operation({
                        "op": "DELETE",
                        "table": table_name,
                        "rid": rid,
                        "old": old_record,
                    })
                    deleted += 1

            binding.refresh_indexes()

            if autocommit:
                self._commit()

            return f"{deleted} registro(s) eliminado(s)"

        except Exception:
            if autocommit:
                self._rollback()
            raise

    def _matches_where(self, record, where) -> bool:
        """Evalua el WHERE contra un registro."""
        if where is None:
            return True

        # Convertir el registro a la forma que espera evaluate:
        # claves normalizadas via column_key
        row = {
            column_key(ast.ColumnRef(name)): value
            for name, value in record.items()
        }

        return truth(evaluate(where, row)) is True