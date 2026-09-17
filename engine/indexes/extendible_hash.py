"""Índice de igualdad: cada entrada contiene una clave y un RID del storage."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator, List, Optional, Tuple, Union

from engine.storage.record import RID

Key = Union[int, float, str]
Entry = Tuple[Key, RID]


@dataclass(eq=False)
class Bucket:
    bucket_capacity: int
    local_depth: int
    records: List[Entry] = field(default_factory=list)
    overflow: Optional[Bucket] = None

    def is_full(self) -> bool:
        return len(self.records) >= self.bucket_capacity

    def entries(self) -> Iterator[Entry]:
        bucket = self
        while bucket is not None:
            yield from bucket.records
            bucket = bucket.overflow

    def add_record(self, entry: Entry) -> None:
        bucket = self
        while bucket.is_full():
            if bucket.overflow is None:
                bucket.overflow = Bucket(self.bucket_capacity, self.local_depth)
            bucket = bucket.overflow
        bucket.records.append(entry)


class ExtendibleHash:
    """Índice de igualdad con directorio global y buckets de pares (clave, RID)."""

    def __init__(self, bucket_capacity: int = 4, *, max_depth: int = 16):
        if type(bucket_capacity) is not int or bucket_capacity < 1:
            raise ValueError("bucket_capacity debe ser un entero positivo")
        if type(max_depth) is not int or not 1 <= max_depth <= 20:
            raise ValueError("max_depth debe ser un entero entre 1 y 20")
        self.bucket_capacity = bucket_capacity
        self.max_depth = max_depth
        self.clear()


    def clear(self) -> None:
        """Vacía el índice sin modificar el storage."""
        self.global_depth = 1
        self.directory = [Bucket(self.bucket_capacity, 1) for _ in range(2)]
        self._size = 0


    def __len__(self) -> int:
        """Número de pares (clave, RID), sin contar dos veces buckets compartidos."""
        return self._size


    def stats(self) -> dict:
        """Cuenta buckets físicos y páginas de overflow sin duplicar referencias."""
        buckets = set(self.directory)
        overflow_count = 0
        for bucket in buckets:
            extra = bucket.overflow
            while extra is not None:
                overflow_count += 1
                extra = extra.overflow
        capacity = (len(buckets) + overflow_count) * self.bucket_capacity
        return {
            "global_depth": self.global_depth,
            "directory_size": len(self.directory),
            "num_buckets": len(buckets),
            "overflow_buckets": overflow_count,
            "entries": self._size,
            "load_factor": self._size / capacity,
        }

