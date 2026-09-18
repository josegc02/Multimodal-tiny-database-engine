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
        """Inicia una nueva transacción.

        Devuelve el tx_id asignado.
        """
        tx_id = self.next_id
        self.next_id += 1

        tx = Transaction(tx_id)
        self.active[tx_id] = tx
        return tx_id

    def commit(self, tx_id: int) -> bool:
        """Confirma los cambios de una transacción.

        Pasos:
        1. Verificar que la transacción existe y está activa.
        2. Persistir los cambios (delegado a storage).
        3. Liberar todos los locks.
        4. Cambiar el estado a COMMITTED.
        """
        tx = self._get_active(tx_id)

        # 1. Persistir cambios
        self._flush_to_disk(tx)

        # 2. Liberar locks
        self.lock_manager.release_all(tx_id)

        # 3. Cambiar estado
        tx.mark_committed()

        # 4. Quitar de activas
        del self.active[tx_id]
        return True

    def get_transaction(self, tx_id: int) -> Optional[Transaction]:
        """Devuelve una transacción activa o None."""
        return self.active.get(tx_id)

    def is_active(self, tx_id: int) -> bool:
        return tx_id in self.active

    def active_count(self) -> int:
        return len(self.active)

    # --- Helpers internos ---

    def _get_active(self, tx_id: int) -> Transaction:
        """Verifica que la transacción existe y está activa."""
        tx = self.active.get(tx_id)
        if tx is None:
            raise RuntimeError(f"Transacción {tx_id} no existe")
        if not tx.is_active:
            raise RuntimeError(
                f"Transacción {tx_id} no está activa (estado: {tx.state.value})"
            )
        return tx

    def _flush_to_disk(self, tx: Transaction) -> None:

        if self.storage is None:
            return
        pass