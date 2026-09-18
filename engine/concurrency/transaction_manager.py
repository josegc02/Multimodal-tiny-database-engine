"""Orquestador de transacciones (BEGIN / COMMIT / ROLLBACK)."""
# concurrency/transaction_manager.py

from typing import Dict, Optional

from .transaction import Transaction
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

    def get_transaction(self, tx_id: int) -> Optional[Transaction]:
        """Devuelve una transacción activa o None."""
        return self.active.get(tx_id)

    def is_active(self, tx_id: int) -> bool:
        return tx_id in self.active

    def active_count(self) -> int:
        return len(self.active)