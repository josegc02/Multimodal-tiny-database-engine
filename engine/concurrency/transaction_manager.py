"""Orquestador de transacciones (BEGIN / COMMIT / ROLLBACK)."""
# concurrency/transaction_manager.py

from typing import Dict, Optional

from .transaction import Transaction, TransactionState
from .lock_manager import LockManager


class TransactionManager:
    """Administra el ciclo de vida de las transacciones."""

    def __init__(self, lock_manager: LockManager, storage=None):
        self.lock_manager = lock_manager
        self.storage = storage
        self.active: Dict[int, Transaction] = {}
        self.next_id = 1

    def begin(self) -> int:
        """Inicia una nueva transacción."""
        tx_id = self.next_id
        self.next_id += 1

        tx = Transaction(tx_id)
        self.active[tx_id] = tx
        return tx_id

    def commit(self, tx_id: int) -> bool:
        """Confirma los cambios de una transacción."""
        tx = self._get_active(tx_id)

        self._flush_to_disk(tx)
        self.lock_manager.release_all(tx_id)
        tx.mark_committed()
        del self.active[tx_id]
        return True

    def rollback(self, tx_id: int) -> bool:
        """Deshace los cambios de una transacción."""
        tx = self.active.get(tx_id)
        if tx is None:
            raise RuntimeError(f"Transacción {tx_id} no existe")

        for op in reversed(tx.undo_log):
            self._undo_operation(op)

        self.lock_manager.release_all(tx_id)
        tx.mark_aborted()
        del self.active[tx_id]
        return True

    def get_transaction(self, tx_id: int) -> Optional[Transaction]:
        return self.active.get(tx_id)

    def is_active(self, tx_id: int) -> bool:
        return tx_id in self.active

    def active_count(self) -> int:
        return len(self.active)

    # --- Helpers internos ---

    def _get_active(self, tx_id: int) -> Transaction:
        tx = self.active.get(tx_id)
        if tx is None:
            raise RuntimeError(f"Transacción {tx_id} no existe")
        if not tx.is_active:
            raise RuntimeError(
                f"Transacción {tx_id} no está activa (estado: {tx.state.value})"
            )
        return tx

    def _get_storage(self, table: str):
        """Devuelve el storage asociado a una tabla."""
        if self.storage is None:
            return None
        if isinstance(self.storage, dict):
            return self.storage.get(table)
        return self.storage

    def _flush_to_disk(self, tx: Transaction) -> None:
        """Persiste los cambios de la transacción.

        Las operaciones ya se aplicaron al ejecutarse (durante el
        execute). Aquí solo se deja el hook para un futuro WAL.
        """
        if self.storage is None:
            return
        pass

    def _undo_operation(self, op: dict) -> None:
        """Deshace una operación concreta."""
        if self.storage is None:
            return

        table = op.get("table")
        op_type = op.get("op")
        storage = self._get_storage(table)

        if storage is None:
            return

        if op_type == "INSERT":
            rid = op.get("rid")
            if rid is not None:
                storage.delete(rid)

        elif op_type == "DELETE":
            old = op.get("old")
            if old is not None:
                storage.insert(old)

        elif op_type == "UPDATE":
            rid = op.get("rid")
            old = op.get("old")
            if rid is not None and old is not None:
                storage.delete(rid)
                storage.insert(old)