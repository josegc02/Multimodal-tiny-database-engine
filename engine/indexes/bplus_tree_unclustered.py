from __future__ import annotations

import math
import os
from pathlib import Path
import tempfile

from engine.indexes.bplus_tree import BPlusTree
from engine.storage.record import RID


class BPlusTreeUnclustered:
    """Hojas con (clave, RID); admite claves repetidas y elimina pares exactos.

    El archivo contiene únicamente el índice. Los registros siguen en el heap
    o secuencial, administrado por el llamador. Actualizar el índice si se mueven
    RIDs en el storage; bulk_load_from_storage(replace=True) lo reconstruye.
    """
    def __init__(self, filepath: str, key_type: str = "int", order: int = 4,
                 *, key_size: int = 64, page_size: int = 4096):
        self.filepath = str(filepath)
        self.key_type = key_type
        self.key_size = key_size
        self.key_field = None
        self.schema_def = [("key", key_type, key_size)] if key_type == "str" else [("key", key_type)]
        self.tree = BPlusTree(self.filepath, self.schema_def, "key", order, page_size,
                              is_clustered=False, allow_duplicates=True)
        self.order = self.tree.header.M
        self.page_size = self.tree.header.page_size

    def insert(self, key, rid: RID) -> bool:
        if not isinstance(rid, RID):
            raise TypeError("El payload debe ser un RID")
        return self.tree.insert(key, rid)

    def search(self, key) -> list[RID]:
        # Igualdad SQL entre int y float integral, sin truncar 1.5 a 1.
        if self.key_type == "int" and type(key) is float and math.isfinite(key) and key.is_integer():
            key = int(key)
        try:
            key = self.tree._normalize_key(key)
        except (TypeError, ValueError, OverflowError):
            return []
        return [rid for _, rid in self.tree.iter_range(key, key)]

    def delete(self, key, rid: RID | None = None) -> int:
        if rid is not None and not isinstance(rid, RID):
            raise TypeError("El payload debe ser un RID")
        deleted = 0
        while self.tree.delete(key, rid):
            deleted += 1
            if rid is not None:
                break
        return deleted

    def iter_range(self, lower=None, upper=None, **kwargs):
        yield from self.tree.iter_range(lower, upper, **kwargs)

    def range_search(self, lower=None, upper=None, **kwargs) -> list[RID]:
        return [rid for _, rid in self.iter_range(lower, upper, **kwargs)]

    def iter_ordered(self, reverse=False):
        entries = self.tree.iter_reverse() if reverse else self.tree.iter_range()
        for _, rid in entries:
            yield rid

    def bulk_load(self, entries, *, replace=False) -> int:
        """replace=True publica el archivo nuevo solo si todo el iterable fue válido."""
        if not replace:
            return sum(self.insert(key, rid) for key, rid in entries)
        parent = str(Path(self.filepath).resolve().parent)
        with tempfile.TemporaryDirectory(prefix=".bplus-build-", dir=parent) as tmp:
            target_path = str(Path(tmp) / "index.bpt")
            with type(self)(target_path, self.key_type, self.order,
                            key_size=self.key_size, page_size=self.page_size) as target:
                count = target.bulk_load(entries)
            os.replace(target_path, self.filepath)
            self.tree.close()
            self.tree = BPlusTree(self.filepath, self.schema_def, "key", self.order, self.page_size,
                                  is_clustered=False, allow_duplicates=True)
        return count

    def bulk_load_from_storage(self, storage, key_field, *, replace=True) -> int:
        if key_field not in storage.schema.fields:
            raise ValueError(f"Columna inexistente: {key_field}")
        position = storage.schema.fields.index(key_field)
        if storage.schema.types[position] != self.key_type:
            raise ValueError("El tipo de la columna no coincide con el índice")
        count = self.bulk_load(((row[key_field], rid) for rid, row in storage.scan()), replace=replace)
        self.key_field = key_field
        return count

    @staticmethod
    def resolve(rid: RID, storage):
        """Resuelve el RID en el storage indicado; devuelve None si fue eliminado."""
        if not isinstance(rid, RID):
            raise TypeError("Se requiere un RID")
        return storage.get(rid)

    def search_records(self, key, storage, *, key_field=None):
        field = key_field or self.key_field
        records = []
        for rid in self.search(key):
            record = self.resolve(rid, storage)
            if record is not None and (field is None or record[field] == key):
                records.append(record)
        return records

    def close(self):
        self.tree.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
