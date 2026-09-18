"""Ejecucion de sentencias AST con soporte de transacciones.

Coordina:
- TransactionManager (para BEGIN / COMMIT / ROLLBACK)
- LockManager (para locks)
- Storage (para INSERT / DELETE)
- QueryExecutor (para SELECT)
"""

from __future__ import annotations

from typing import Optional

from engine.query.ast import TransactionStatement


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