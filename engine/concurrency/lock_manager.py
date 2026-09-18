"""Gestion de locks (bloqueos) para control de concurrencia."""
# concurrency/lock_manager.py

from enum import Enum
from typing import Dict, List, Tuple

class LockMode(Enum):
    """Tipos de lock soportados."""
    SHARED = "S"
    EXCLUSIVE = "X"


# Tabla de compatibilidad: (modo_solicitado, modo_existente) -> compatible
_COMPATIBILITY = {
    (LockMode.SHARED, LockMode.SHARED): True,       # S con S = ok
    (LockMode.SHARED, LockMode.EXCLUSIVE): False,   # S con X = no
    (LockMode.EXCLUSIVE, LockMode.SHARED): False,   # X con S = no
    (LockMode.EXCLUSIVE, LockMode.EXCLUSIVE): False # X con X = no
}


class LockManager:
    """Administra los locks de todas las transacciones."""

    def __init__(self):
        self.lock_table: Dict[str, Dict[int, LockMode]] = {}

    def acquire(self, tx_id: int, resource: str, mode: LockMode) -> bool:
        """Intenta adquirir un lock.

        Devuelve True si lo consigue, False si no es posible.
        """
        if self._already_holds(tx_id, resource, mode):
            return True

        if not self._can_grant(tx_id, resource, mode):
            return False

        self._grant(tx_id, resource, mode)
        return True

    def release(self, tx_id: int, resource: str) -> None:
        """Libera el lock de una transacción sobre un recurso."""
        if resource not in self.lock_table:
            return
        if tx_id not in self.lock_table[resource]:
            return

        del self.lock_table[resource][tx_id]

        if not self.lock_table[resource]:
            del self.lock_table[resource]

    def release_all(self, tx_id: int) -> None:
        """Libera TODOS los locks de una transacción.

        Se llama al hacer commit o rollback.
        """
        for resource in list(self.lock_table.keys()):
            if tx_id in self.lock_table[resource]:
                del self.lock_table[resource][tx_id]
            if not self.lock_table[resource]:
                del self.lock_table[resource]

    def get_locks(self, tx_id: int) -> List[Tuple[str, LockMode]]:
        """Devuelve todos los locks que tiene una transacción."""
        result = []
        for resource, holders in self.lock_table.items():
            if tx_id in holders:
                result.append((resource, holders[tx_id]))
        return result

    # --- Helpers internos ---

    def _already_holds(self, tx_id: int, resource: str, mode: LockMode) -> bool:
        current = self.lock_table.get(resource, {}).get(tx_id)
        if current is None:
            return False
        if current == mode:
            return True
        if current == LockMode.EXCLUSIVE and mode == LockMode.SHARED:
            return True
        return False

    def _can_grant(self, tx_id: int, resource: str, mode: LockMode) -> bool:
        holders = self.lock_table.get(resource, {})
        for holder_id, holder_mode in holders.items():
            if holder_id == tx_id:
                continue
            if not _COMPATIBILITY[(mode, holder_mode)]:
                return False
        return True

    def _grant(self, tx_id: int, resource: str, mode: LockMode) -> None:
        self.lock_table.setdefault(resource, {})[tx_id] = mode