from __future__ import annotations

from typing import Any, List, Optional, Tuple
from engine.storage.record import RID


class BPlusTreeUnclustered:
    """Índice B+ Tree no agrupado (unclustered): las hojas almacenan pares (clave, RID)."""
    def __init__(self, filepath: str, key_type: str = "int", order: int = 4):
        self.filepath = filepath
        self.key_type = key_type
        self.order = order
