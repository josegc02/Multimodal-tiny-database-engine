"""Orquestador de transacciones (BEGIN / COMMIT / ROLLBACK)."""
# concurrency/transaction_manager.py

import threading
from typing import Dict, Optional

from .transaction import Transaction, TransactionState
from .lock_manager import LockManager


class TransactionManager:
    """Administra el ciclo de vida de las transacciones.

    Es seguro entre hilos: los ids y la tabla de transacciones activas se
    protegen con un mutex. El undo se aplica mientras la transacción todavía
    tiene sus locks (2PL estricto) y luego se liberan.
    """

    def __init__(self, lock_manager: LockManager, storage=None):
        self.lock_manager = lock_manager
        self.storage = storage
        self.active: Dict[int, Transaction] = {}
        self.next_id = 1
        self._mutex = threading.Lock()

    def begin(self) -> int:
        """Inicia una nueva transacción."""
        with self._mutex:
            tx_id = self.next_id
            self.next_id += 1
            self.active[tx_id] = Transaction(tx_id)
        return tx_id

    def commit(self, tx_id: int) -> bool:
        """Confirma los cambios de una transacción."""
        tx = self._get_active(tx_id)
        self._flush_to_disk(tx)
        tx.mark_committed()
        self._finish(tx_id)
        return True

    def rollback(self, tx_id: int) -> bool:
        """Deshace los cambios de una transacción y libera sus locks."""
        tx = self.get_transaction(tx_id)
        if tx is None:
            raise RuntimeError(f"Transacción {tx_id} no existe")
        errors = []
        touched = []
        try:
            for op in reversed(tx.undo_log):
                try:
                    self._undo_operation(op)
                    if op.get("table") not in touched:
                        touched.append(op.get("table"))
                except Exception as exc:  # se intenta deshacer todo lo posible
                    errors.append(exc)
            self._refresh_indexes(touched)
        finally:
            if tx.is_active:
                tx.mark_aborted()
            self._finish(tx_id)
        if errors:
            raise RuntimeError(f"Rollback de la transacción {tx_id} incompleto: {errors[0]}") from errors[0]
        return True

    def get_transaction(self, tx_id: int) -> Optional[Transaction]:
        with self._mutex:
            return self.active.get(tx_id)

    def is_active(self, tx_id: int) -> bool:
        with self._mutex:
            return tx_id in self.active

    def active_count(self) -> int:
        with self._mutex:
            return len(self.active)

    # --- Helpers internos ---

    def _finish(self, tx_id: int) -> None:
        self.lock_manager.release_all(tx_id)
        with self._mutex:
            tx = self.active.pop(tx_id, None)
        if tx is not None:
            tx.clear_locks()

    def _get_active(self, tx_id: int) -> Transaction:
        tx = self.get_transaction(tx_id)
        if tx is None:
            raise RuntimeError(f"Transacción {tx_id} no existe")
        if not tx.is_active:
            raise RuntimeError(
                f"Transacción {tx_id} no está activa (estado: {tx.state.value})"
            )
        return tx

    def _binding(self, table: str):
        """TableBinding si storage es un Catalog; None en otro caso."""
        if self.storage is not None and callable(getattr(self.storage, "table", None)):
            try:
                return self.storage.table(table)
            except Exception:
                return None
        return None

    def _get_storage(self, table: str):
        """Devuelve el storage asociado a una tabla.

        Acepta:
        - Catalog (con .table(name).storage)
        - dict {nombre: storage}
        - un storage unico
        """
        if self.storage is None:
            return None
        binding = self._binding(table)
        if binding is not None:
            return binding.storage
        if callable(getattr(self.storage, "table", None)):
            return None
        if isinstance(self.storage, dict):
            return self.storage.get(table)
        return self.storage

    def _flush_to_disk(self, tx: Transaction) -> None:
        """Persiste los cambios de la transacción.

        Las operaciones ya se aplicaron al ejecutarse (durante el
        execute). Aquí solo se deja el hook para un futuro WAL.
        """
        return None

    def _refresh_indexes(self, tables) -> None:
        for table in tables:
            binding = self._binding(table)
            if binding is not None and binding.indexes:
                binding.refresh_indexes()

    def _locate(self, table: str, storage, rid, record):
        """RID actual del registro: los del SequentialFile se desplazan."""
        binding = self._binding(table)
        if binding is not None:
            return binding.locate(rid, record)
        if rid is not None and storage.get(rid) == record:
            return rid
        for current_rid, current in storage.scan():
            if current == record:
                return current_rid
        return None

    def _undo_operation(self, op: dict) -> None:
        """Deshace una operación concreta."""
        table = op.get("table")
        storage = self._get_storage(table)
        if storage is None:
            return
        binding = self._binding(table)
        latch = binding.latch if binding is not None else threading.RLock()
        op_type = op.get("op")

        with latch:
            if op_type == "INSERT":
                record = op.get("record")
                rid = op.get("rid")
                if record is not None:
                    rid = self._locate(table, storage, rid, record)
                if rid is not None:
                    storage.delete(rid)

            elif op_type == "DELETE":
                old = op.get("old")
                if old is not None:
                    storage.insert(old)

            elif op_type == "UPDATE":
                old = op.get("old")
                new = op.get("new")
                rid = op.get("rid")
                if new is not None:
                    rid = self._locate(table, storage, rid, new)
                if rid is not None:
                    storage.delete(rid)
                if old is not None:
                    storage.insert(old)
