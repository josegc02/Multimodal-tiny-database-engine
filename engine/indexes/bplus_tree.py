from __future__ import annotations

from typing import Any, List, Optional, Tuple


class BPlusTreeClustered:
    """Índice B+ Tree agrupado (clustered): las hojas contienen los registros reales ordenados por clave."""
    def __init__(self, filepath: str, key_type: str = "int", order: int = 4):
        self.filepath = filepath
        self.key_type = key_type
        self.order = order
