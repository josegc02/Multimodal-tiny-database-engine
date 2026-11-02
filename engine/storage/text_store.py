"""Archivo con los valores de las columnas TEXT, que no caben en una página de registros."""

from __future__ import annotations

import hashlib
import os
import threading
from typing import BinaryIO, Dict, Optional, Tuple


class TextStore:
    """Guarda textos y los devuelve por su posición y largo en bytes.

    Los storages vuelven a serializar registros al moverlos (el B+ agrupado, en
    cada escritura de un nodo), así que un mismo contenido se guarda una sola vez.
    Esa memoria vive solo mientras el archivo está abierto: tras reabrirlo, volver
    a guardar un texto ocupa más espacio pero no afecta los datos. Las eliminaciones
    tampoco liberan espacio.
    """

    def __init__(self, filepath: str):
        self.filepath = filepath
        self._latch = threading.RLock()
        self._fh: Optional[BinaryIO] = None
        self._known: Dict[bytes, Tuple[int, int]] = {}

    # Abre el archivo la primera vez que se usa: una tabla sin textos no lo crea.
    def _file(self) -> BinaryIO:
        if self._fh is None:
            self._fh = open(self.filepath, "r+b" if os.path.exists(self.filepath) else "w+b")
        return self._fh

    # Guarda un texto y devuelve su (posición, largo). Si ya estaba, reutiliza esa posición.
    def put(self, text: str) -> Tuple[int, int]:
        data = text.encode("utf-8")
        key = hashlib.blake2b(data, digest_size=16).digest()
        with self._latch:
            reference = self._known.get(key)
            if reference is None:
                fh = self._file()
                reference = (fh.seek(0, os.SEEK_END), len(data))
                fh.write(data)
                fh.flush()
                self._known[key] = reference
            return reference

    # Lee el texto guardado en esa posición.
    def get(self, offset: int, length: int) -> str:
        with self._latch:
            fh = self._file()
            fh.seek(offset)
            return fh.read(length).decode("utf-8")

    def close(self) -> None:
        with self._latch:
            if self._fh is not None:
                self._fh.close()
                self._fh = None
