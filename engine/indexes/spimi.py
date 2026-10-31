"""Índice invertido en disco construido con SPIMI (issue #45).

El archivo se divide en páginas de 4096 B. La página 0 es la cabecera y las demás
forman tres zonas contiguas: diccionario, postings y tabla de documentos. La cabecera
guarda dónde empieza y cuántas páginas ocupa cada zona.

Una posting es (doc_id, tf). Las listas se leen de corrido porque ocupan páginas seguidas.
"""

from __future__ import annotations

import math
import os
import struct
from typing import Iterable, List, Optional, Tuple

from engine.text.preprocessing import IDIOMAS

PAGE_SIZE = 4096
MAGIC = b"SPI1"

# magic, idioma, documentos, siguiente doc_id, términos, longitud total, páginas,
# inicio y páginas de: diccionario, postings y documentos
HEADER = struct.Struct(">4s2sIIIQIIIIIII")
POSTING = struct.Struct(">II")  # doc_id, tf

Posting = Tuple[int, int]


# Convierte una lista de postings en bytes para escribirla en disco.
def encode_postings(postings: Iterable[Posting]) -> bytes:
    return b"".join(POSTING.pack(doc_id, tf) for doc_id, tf in postings)


# Convierte los bytes de una lista en sus postings.
def decode_postings(data: bytes) -> List[Posting]:
    return list(POSTING.iter_unpack(data))


# Calcula cuántas páginas hacen falta para guardar `size` bytes.
def pages_for(size: int) -> int:
    return math.ceil(size / PAGE_SIZE)


class SpimiIndex:
    """Índice invertido persistente. El idioma se fija al crearlo y queda en la cabecera."""

    # Abre el archivo si existe o crea uno vacío. Sin `language` usa el del archivo.
    def __init__(self, filepath: str, language: Optional[str] = None):
        if language is not None and language not in IDIOMAS:
            raise ValueError(f"Idioma no soportado: {language}")
        self.filepath = os.fspath(filepath)
        exists = os.path.exists(self.filepath) and os.path.getsize(self.filepath) > 0
        self._fh = open(self.filepath, "r+b" if exists else "w+b")
        try:
            if exists:
                self._read_header()
                if language is not None and language != self.language:
                    raise ValueError("El idioma no coincide con el del archivo")
            else:
                self.language = language or "es"
                self._reset()
        except Exception:
            self._fh.close()
            raise

    # --- Archivo -----------------------------------------------------------------

    # Carga los totales y la ubicación de cada zona desde la página 0.
    def _read_header(self) -> None:
        self._fh.seek(0)
        data = self._fh.read(HEADER.size)
        if len(data) != HEADER.size or data[:4] != MAGIC:
            raise ValueError(f"{self.filepath} no es un archivo SPIMI")
        (_, language, self.doc_count, self.next_doc_id, self.term_count, self.total_length, self.page_count,
         self.dictionary_start, self.dictionary_pages, self.postings_start, self.postings_pages,
         self.documents_start, self.documents_pages) = HEADER.unpack(data)
        self.language = language.decode("ascii")

    # Guarda los totales y la ubicación de cada zona en la página 0.
    def _write_header(self) -> None:
        self._fh.seek(0)
        self._fh.write(HEADER.pack(MAGIC, self.language.encode("ascii"), self.doc_count, self.next_doc_id,
                                   self.term_count, self.total_length, self.page_count,
                                   self.dictionary_start, self.dictionary_pages,
                                   self.postings_start, self.postings_pages,
                                   self.documents_start, self.documents_pages).ljust(PAGE_SIZE, b"\0"))

    # Deja el índice vacío: solo queda la cabecera.
    def _reset(self) -> None:
        self._fh.truncate(0)
        self.doc_count = self.next_doc_id = self.term_count = self.total_length = 0
        self.page_count = 1
        self.dictionary_start = self.dictionary_pages = 0
        self.postings_start = self.postings_pages = 0
        self.documents_start = self.documents_pages = 0
        self._write_header()

    # Lee `count` páginas seguidas con una sola operación de disco.
    def _read_pages(self, start: int, count: int = 1) -> bytes:
        self._fh.seek(start * PAGE_SIZE)
        return self._fh.read(count * PAGE_SIZE)

    # Escribe `data` en páginas seguidas, rellena la última y devuelve cuántas ocupó.
    def _write_pages(self, start: int, data: bytes) -> int:
        count = pages_for(len(data))
        self._fh.seek(start * PAGE_SIZE)
        self._fh.write(data.ljust(count * PAGE_SIZE, b"\0"))
        self.page_count = max(self.page_count, start + count)
        return count

    # --- Ciclo de vida -----------------------------------------------------------

    # Número de documentos del índice.
    def __len__(self) -> int:
        return self.doc_count

    # Asegura que la cabecera y las páginas escritas lleguen al archivo.
    def flush(self) -> None:
        self._write_header()
        self._fh.flush()

    # Guarda los cambios y cierra el archivo.
    def close(self) -> None:
        if not self._fh.closed:
            self.flush()
            self._fh.close()

    def __enter__(self) -> SpimiIndex:
        return self

    def __exit__(self, *exc) -> None:
        self.close()
