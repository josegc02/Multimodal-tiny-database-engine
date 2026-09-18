"""Gestion de locks (bloqueos) para control de concurrencia."""
# concurrency/lock_manager.py

from enum import Enum


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