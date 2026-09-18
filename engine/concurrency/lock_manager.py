"""Gestion de locks (bloqueos) para control de concurrencia."""
# concurrency/lock_manager.py
import threading
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple


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
        self.wait_queue: Dict[str, List[int]] = {}
        self._mutex = threading.Lock()
        self._condition = threading.Condition(self._mutex)

    def acquire(self, tx_id: int, resource: str, mode: LockMode,
                timeout: Optional[float] = None) -> bool:
        """Intenta adquirir un lock.

        Devuelve True si lo consigue, False si expira el timeout.
        Si timeout es None, espera indefinidamente.
        """
        with self._condition:
            self._ensure_resource(resource)

            # Caso 1: ya tengo el lock (o uno mas fuerte)
            if self._already_holds(tx_id, resource, mode):
                return True

            # Caso 2: puedo obtenerlo sin esperar
            if self._can_grant(tx_id, resource, mode):
                self._grant(tx_id, resource, mode)
                return True

            # Caso 3: debo esperar
            self._enqueue(tx_id, resource)

            # Si hay deadlock, abortamos al solicitante
            if self._would_deadlock(tx_id):
                self._dequeue(tx_id, resource)
                raise RuntimeError(
                    f"Deadlock detectado: tx {tx_id} no puede esperar por {resource}"
                )

            # Esperar hasta ser notificado o timeout
            if timeout is None:
                while not self._can_grant(tx_id, resource, mode):
                    self._condition.wait()
            else:
                got = self._condition.wait_for(
                    lambda: self._can_grant(tx_id, resource, mode),
                    timeout=timeout
                )
                if not got:
                    self._dequeue(tx_id, resource)
                    return False

            # Al despertar, verificar de nuevo
            self._dequeue(tx_id, resource)
            self._grant(tx_id, resource, mode)
            return True

    def release(self, tx_id: int, resource: str) -> None:
        """Libera el lock de una transacción sobre un recurso."""
        with self._condition:
            if resource not in self.lock_table:
                return
            if tx_id not in self.lock_table[resource]:
                return

            del self.lock_table[resource][tx_id]

            if not self.lock_table[resource]:
                del self.lock_table[resource]

            # Despertar a quien esté esperando
            self._condition.notify_all()

    def release_all(self, tx_id: int) -> None:
        """Libera TODOS los locks de una transacción."""
        with self._condition:
            for resource in list(self.lock_table.keys()):
                if tx_id in self.lock_table[resource]:
                    del self.lock_table[resource][tx_id]
                if not self.lock_table[resource]:
                    del self.lock_table[resource]
            self._condition.notify_all()

    def get_locks(self, tx_id: int) -> List[Tuple[str, LockMode]]:
        """Devuelve todos los locks que tiene una transacción."""
        with self._mutex:
            result = []
            for resource, holders in self.lock_table.items():
                if tx_id in holders:
                    result.append((resource, holders[tx_id]))
            return result


    # --- Deteccion de deadlocks ---

    def detect_deadlock(self) -> Optional[List[int]]:
        """Busca ciclos en el wait-for graph."""
        with self._mutex:
            graph = self._build_wait_for_graph()
            return self._find_cycle(graph)

    def _build_wait_for_graph(self) -> Dict[int, Set[int]]:
        """Construye: tx_id -> {tx_ids a los que espera}."""
        graph: Dict[int, Set[int]] = {}

        for resource, holders in self.lock_table.items():
            waiting = self.wait_queue.get(resource, [])
            for waiter in waiting:
                for holder in holders:
                    if waiter != holder:
                        graph.setdefault(waiter, set()).add(holder)

        return graph

    def _find_cycle(self, graph: Dict[int, Set[int]]) -> Optional[List[int]]:
        """DFS para encontrar un ciclo en el grafo."""
        visited: Set[int] = set()
        stack: Set[int] = set()
        path: List[int] = []

        def dfs(node: int) -> Optional[List[int]]:
            visited.add(node)
            stack.add(node)
            path.append(node)

            for neighbor in graph.get(node, set()):
                if neighbor not in visited:
                    result = dfs(neighbor)
                    if result:
                        return result
                elif neighbor in stack:
                    idx = path.index(neighbor)
                    return path[idx:]

            path.pop()
            stack.discard(node)
            return None

        for node in graph:
            if node not in visited:
                cycle = dfs(node)
                if cycle:
                    return cycle
        return None

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

    def _enqueue(self, tx_id: int, resource: str) -> None:
        q = self.wait_queue.setdefault(resource, [])
        if tx_id not in q:
            q.append(tx_id)

    def _dequeue(self, tx_id: int, resource: str) -> None:
        q = self.wait_queue.get(resource, [])
        if tx_id in q:
            q.remove(tx_id)

    def _ensure_resource(self, resource: str) -> None:
        self.lock_table.setdefault(resource, {})
        self.wait_queue.setdefault(resource, [])

    def _would_deadlock(self, tx_id: int) -> bool:
        """Verifica si agregar esta espera crearia un ciclo."""
        cycle = self.detect_deadlock()
        return cycle is not None and tx_id in cycle