"""Archivo con la ruta y el vector de cada valor de las columnas IMAGE y AUDIO.

Cada entrada guarda el tipo (1 byte), el largo de la ruta, la dimensión del
vector, la ruta en UTF-8 y el vector en float32. El registro de la tabla solo
guarda la posición y el largo de su entrada, como las columnas TEXT.

El vector se extrae una sola vez, al insertar. Una misma ruta del mismo tipo
reutiliza su entrada, también tras reabrir el archivo: se asume que los
archivos multimedia no cambian después de insertarse. Las eliminaciones no
liberan espacio.
"""

from __future__ import annotations

import os
import struct
import threading
from typing import BinaryIO, Callable, Dict, Optional, Tuple

import numpy as np

from engine.features.registry import MEDIA_TYPES, extract_features

ENTRY_HEADER = struct.Struct(">BII")  # tipo, bytes de la ruta, dimensión
VECTOR_TYPE = np.dtype(">f4")
KIND_CODES = {kind: code for code, kind in enumerate(MEDIA_TYPES)}


class MediaStore:
    """Guarda (ruta, vector) y los devuelve por la posición de su entrada."""

    def __init__(self, filepath: str, extract: Optional[Callable[[str, str], np.ndarray]] = None):
        self.filepath = filepath
        self._extract = extract or extract_features
        self._latch = threading.RLock()
        self._fh: Optional[BinaryIO] = None
        self._known: Dict[Tuple[str, str], Tuple[int, int]] = {}
        if os.path.exists(filepath):
            try:
                self._load()
            except Exception:
                self.close()
                raise

    # Reconstruye el mapa (tipo, ruta) -> entrada a partir del archivo.
    def _load(self) -> None:
        fh = self._file()
        size = fh.seek(0, os.SEEK_END)
        offset = 0
        while offset < size:
            fh.seek(offset)
            header = fh.read(ENTRY_HEADER.size)
            if len(header) != ENTRY_HEADER.size:
                raise ValueError(f"Archivo multimedia truncado: {self.filepath}")
            code, path_size, dimension = ENTRY_HEADER.unpack(header)
            length = ENTRY_HEADER.size + path_size + dimension * VECTOR_TYPE.itemsize
            if code >= len(MEDIA_TYPES) or offset + length > size:
                raise ValueError(f"Archivo multimedia inválido: {self.filepath}")
            path = fh.read(path_size).decode("utf-8")
            self._known[(MEDIA_TYPES[code], path)] = (offset, length)
            offset += length

    # Abre el archivo la primera vez que se usa: una tabla sin multimedia no lo crea.
    def _file(self) -> BinaryIO:
        if self._fh is None:
            self._fh = open(self.filepath, "r+b" if os.path.exists(self.filepath) else "w+b")
        return self._fh

    def put(self, kind: str, path: str) -> Tuple[int, int]:
        """Extrae el vector del archivo (si es nuevo) y devuelve (posición, largo)."""
        if kind not in KIND_CODES:
            raise ValueError(f"Tipo multimedia no soportado: {kind}")
        with self._latch:
            reference = self._known.get((kind, path))
            if reference is not None:
                return reference
            try:
                vector = self._extract(kind, path)
            except Exception as exc:
                raise ValueError(f"No se pudo extraer el vector de {path!r} ({kind.upper()}): {exc}") from exc
            encoded = path.encode("utf-8")
            data = (ENTRY_HEADER.pack(KIND_CODES[kind], len(encoded), len(vector)) + encoded
                    + np.asarray(vector, dtype=VECTOR_TYPE).tobytes())
            fh = self._file()
            reference = (fh.seek(0, os.SEEK_END), len(data))
            fh.write(data)
            fh.flush()
            self._known[(kind, path)] = reference
            return reference

    def _entry(self, offset: int, length: int) -> Tuple[str, np.ndarray]:
        with self._latch:
            fh = self._file()
            fh.seek(offset)
            data = fh.read(length)
        _, path_size, dimension = ENTRY_HEADER.unpack_from(data)
        start = ENTRY_HEADER.size + path_size
        vector = np.frombuffer(data, VECTOR_TYPE, dimension, start).astype(np.float64)
        return data[ENTRY_HEADER.size:start].decode("utf-8"), vector

    def get(self, offset: int, length: int) -> str:
        """Ruta guardada en esa entrada (el valor que ve SQL)."""
        return self._entry(offset, length)[0]

    def vector(self, kind: str, path: str) -> np.ndarray:
        """Vector de un valor ya insertado."""
        with self._latch:
            reference = self._known.get((kind, path))
        if reference is None:
            raise KeyError(f"La ruta {path!r} no está en el almacén multimedia")
        return self._entry(*reference)[1]

    def close(self) -> None:
        with self._latch:
            if self._fh is not None:
                self._fh.close()
                self._fh = None
