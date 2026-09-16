from __future__ import annotations

from typing import Any, List, Optional
from engine.storage.record import RID


class ExtendibleHash:
    """Índice Hash Dinámico (Extendible Hashing): directorio global y buckets con profundidad local."""
    def __init__(self, filepath: str, bucket_capacity: int = 4):
        self.filepath = filepath
        self.bucket_capacity = bucket_capacity
        self.global_depth = 1
