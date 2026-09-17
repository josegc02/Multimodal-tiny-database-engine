"""Índice de igualdad: cada entrada contiene una clave y un RID del storage."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Iterator, List, Optional, Protocol, Tuple, Union

from engine.storage.record import RID, Schema

Key = Union[int, float, str]
Entry = Tuple[Key, RID]


class RecordSource(Protocol):
    """Interfaz común de HeapFile y SequentialFile para construir índices."""

    schema: Schema

    def scan(self) -> Iterator[Tuple[RID, Dict[str, Any]]]: ...


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

    def __init__(
        self, bucket_capacity: int = 4, *, max_depth: int = 16,
        filepath: Optional[Union[str, os.PathLike]] = None,
    ):
        if type(bucket_capacity) is not int or bucket_capacity < 1:
            raise ValueError("bucket_capacity debe ser un entero positivo")
        if type(max_depth) is not int or not 1 <= max_depth <= 20:
            raise ValueError("max_depth debe ser un entero entre 1 y 20")
        self.bucket_capacity = bucket_capacity
        self.max_depth = max_depth
        self.filepath = os.fspath(filepath) if filepath is not None else None
        self.clear()
        if self.filepath is not None and os.path.exists(self.filepath):
            self._load()


    @staticmethod
    def _hash_key(key: Key) -> int:
        # No usar hash(str): su semilla cambia entre procesos de Python.
        if type(key) is str:
            encoded = b"s:" + key.encode("utf-8")
        elif type(key) is int:
            encoded = f"n:{key}/1".encode("ascii")
        elif type(key) is float:
            if not math.isfinite(key):
                raise ValueError("La clave float debe ser finita")
            numerator, denominator = key.as_integer_ratio()
            encoded = f"n:{numerator}/{denominator}".encode("ascii")
        else:
            raise TypeError("La clave debe ser int, float o str")
        return int.from_bytes(hashlib.blake2b(encoded, digest_size=8).digest(), "big")


    @staticmethod
    def _validate_rid(rid: RID) -> None:
        if not isinstance(rid, RID):
            raise TypeError("Se requiere un RID")
        if (type(rid.page_id) is not int or rid.page_id < 0
                or type(rid.slot_id) is not int or rid.slot_id < 0
                or rid.file not in ("main", "aux")):
            raise ValueError("RID inválido: se requieren posiciones no negativas y main/aux")


    def clear(self) -> None:
        """Vacía el índice sin modificar el storage."""
        self.global_depth = 1
        self.directory = [Bucket(self.bucket_capacity, 1) for _ in range(2)]
        self._size = 0


    def __len__(self) -> int:
        """Número de pares (clave, RID), sin contar dos veces buckets compartidos."""
        return self._size


    def _index(self, hashed: int) -> int:
        return hashed & ((1 << self.global_depth) - 1)


    def insert(self, key: Key, rid: RID) -> bool:
        """Agrega un par; retorna False si ese mismo par ya estaba indexado."""
        hashed = self._hash_key(key)
        self._validate_rid(rid)
        bucket = self.directory[self._index(hashed)]
        if any(k == key and r == rid for k, r in bucket.entries()):
            return False

        while True:
            bucket = self.directory[self._index(hashed)]
            if not bucket.is_full():
                bucket.add_record((key, rid))
                break

            mask = (1 << self.max_depth) - 1
            if bucket.local_depth == self.max_depth or all(
                (self._hash_key(k) & mask) == (hashed & mask)
                for k, _ in bucket.entries()
            ):
                # Duplicados y colisiones reales nunca se resuelven duplicando
                # indefinidamente el directorio.
                bucket.add_record((key, rid))
                break
            self._split_bucket(self._index(hashed))

        self._size += 1
        return True


    def _split_bucket(self, index: int) -> None:
        old = self.directory[index]
        entries = list(old.entries())
        if old.local_depth == self.global_depth:
            self.directory += self.directory[:]
            self.global_depth += 1

        old.local_depth += 1
        new = Bucket(self.bucket_capacity, old.local_depth)
        split_bit = 1 << (old.local_depth - 1)
        prefix = index & (split_bit - 1)
        for i in range(prefix | split_bit, len(self.directory), 1 << old.local_depth):
            self.directory[i] = new

        old.records.clear()
        old.overflow = None
        for key, rid in entries:
            target = self.directory[self._index(self._hash_key(key))]
            target.add_record((key, rid))


    def search(self, key: Key) -> List[RID]:
        """Devuelve todos los RIDs asociados a la clave, o una lista vacía."""
        bucket = self.directory[self._index(self._hash_key(key))]
        return [rid for stored_key, rid in bucket.entries() if stored_key == key]


    def bulk_load(self, entries: Iterable[Entry], *, replace: bool = False) -> int:
        """Carga pares (clave, RID) desde un iterable, sin materializar su entrada.

        Retorna la cantidad de pares nuevos. Con replace=True construye un índice
        nuevo y lo publica solo al terminar; un error conserva el índice anterior.
        Con replace=False agrega sobre el actual y conserva los pares ya agregados
        si el iterable falla. Los pares repetidos son ignorados en ambos modos.
        """
        target = type(self)(self.bucket_capacity, max_depth=self.max_depth) if replace else self
        inserted = 0
        for key, rid in entries:
            inserted += target.insert(key, rid)
        if replace:
            self.directory = target.directory
            self.global_depth = target.global_depth
            self._size = target._size
        return inserted


    def bulk_load_from_storage(
        self, storage: RecordSource, key_field: str, *, replace: bool = True
    ) -> int:
        """Indexa registros activos de un HeapFile o SequentialFile ya cargado.

        El scan entrega los RIDs actuales (main y aux incluidos). Por defecto
        reemplaza el índice para descartar RIDs obsoletos después de cambios en
        el storage. No debe modificarse el storage mientras se recorre.
        """
        if key_field not in storage.schema.fields:
            raise ValueError(f"El campo '{key_field}' no existe en el schema")
        entries = ((record[key_field], rid) for rid, record in storage.scan())
        return self.bulk_load(entries, replace=replace)


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


    def flush(self) -> None:
        """Guarda un snapshot JSON mediante reemplazo atómico si hay filepath.

        El índice opera en memoria; no escribe páginas individuales al insertar.
        La persistencia ocurre al llamar flush(), close() o salir de un contexto.
        Un solo escritor debe usar cada archivo de índice.
        """
        if self.filepath is None:
            return
        snapshot = {
            "format": "extendible-hash",
            "version": 1,
            "bucket_capacity": self.bucket_capacity,
            "max_depth": self.max_depth,
            "entries": [
                [key, rid.page_id, rid.slot_id, rid.file]
                for bucket in dict.fromkeys(self.directory)
                for key, rid in bucket.entries()
            ],
        }
        parent = os.path.dirname(os.path.abspath(self.filepath))
        os.makedirs(parent, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=parent,
                prefix=".extendible-hash-", suffix=".tmp", delete=False,
            ) as fh:
                temporary = fh.name
                json.dump(snapshot, fh, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(temporary, self.filepath)
        finally:
            if temporary is not None and os.path.exists(temporary):
                os.unlink(temporary)


    def _load(self) -> None:
        """Reconstruye el directorio con la configuración y los pares guardados."""
        try:
            with open(self.filepath, encoding="utf-8") as fh:
                snapshot = json.load(fh)
            if (not isinstance(snapshot, dict)
                    or snapshot.get("format") != "extendible-hash"
                    or type(snapshot.get("version")) is not int
                    or snapshot["version"] != 1):
                raise ValueError("Formato o versión de índice no soportado")
            loaded = type(self)(snapshot["bucket_capacity"], max_depth=snapshot["max_depth"])
            if not isinstance(snapshot["entries"], list):
                raise ValueError("La lista de entradas es inválida")
            for entry in snapshot["entries"]:
                if not isinstance(entry, list) or len(entry) != 4:
                    raise ValueError("Entrada inválida")
                key, page_id, slot_id, file = entry
                loaded.insert(key, RID(page_id, slot_id, file))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Archivo de extendible hash inválido: {self.filepath}") from exc
        self.bucket_capacity = loaded.bucket_capacity
        self.max_depth = loaded.max_depth
        self.directory = loaded.directory
        self.global_depth = loaded.global_depth
        self._size = loaded._size


    def close(self) -> None:
        """Persiste los cambios pendientes. No mantiene descriptores abiertos."""
        self.flush()


    def __enter__(self) -> ExtendibleHash:
        return self


    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

