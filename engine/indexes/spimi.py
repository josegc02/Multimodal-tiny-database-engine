"""Índice invertido en disco construido con SPIMI (issue #45).

El archivo se divide en páginas de 4096 B. La página 0 es la cabecera y las demás
forman tres zonas contiguas: postings, diccionario y tabla de documentos. La cabecera
guarda dónde empieza y cuántas páginas ocupa cada zona.

Una posting es (doc_id, tf). Las listas van una tras otra en la zona de postings y se
leen de corrido; el diccionario guarda, por término, su df y el byte donde empieza su lista.

La construcción sigue SPIMI: cada bloque es un hash término -> postings que se ordena y
se escribe a un archivo temporal al llenarse. Los doc_id crecen, así que las listas
quedan ordenadas por doc_id dentro de cada bloque y entre bloques. Al final, una mezcla
k-way con cola de prioridad une los bloques y basta concatenar las listas de un término.
"""

from __future__ import annotations

import heapq
import math
import os
import shutil
import struct
from collections import Counter
from itertools import groupby
from operator import itemgetter
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

from engine.text.preprocessing import IDIOMAS, tokens

PAGE_SIZE = 4096
MAGIC = b"SPI1"

# magic, idioma, documentos, siguiente doc_id, términos, longitud total, páginas,
# inicio y páginas de: diccionario, postings y documentos
HEADER = struct.Struct(">4s2sIIIQIIIIIII")
POSTING = struct.Struct(">II")  # doc_id, tf
BLOCK_ENTRY = struct.Struct(">BI")  # bytes del término, postings
DICTIONARY_PAGE = struct.Struct(">H")  # entradas de la página
DICTIONARY_ENTRY = struct.Struct(">BIQ")  # bytes del término, df, byte donde empieza su lista

DEFAULT_BLOCK_SIZE = 8 * 1024 * 1024  # tamaño del bloque en disco; en memoria ocupa más
READ_BUFFER = 16 * PAGE_SIZE  # buffer de lectura de cada bloque durante la mezcla
MAX_TERM_BYTES = 255  # un token más largo no es una palabra (hashes, base64)

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


# Junta las entradas de una página del diccionario y la rellena hasta 4 KB.
def encode_dictionary_page(entries: List[bytes]) -> bytes:
    return (DICTIONARY_PAGE.pack(len(entries)) + b"".join(entries)).ljust(PAGE_SIZE, b"\0")


# Lee una página del diccionario y devuelve sus entradas (término, df, inicio).
def decode_dictionary_page(data: bytes) -> List[Tuple[str, int, int]]:
    entries = []
    position = DICTIONARY_PAGE.size
    for _ in range(DICTIONARY_PAGE.unpack_from(data)[0]):
        term_size, df, start = DICTIONARY_ENTRY.unpack_from(data, position)
        position += DICTIONARY_ENTRY.size
        entries.append((data[position:position + term_size].decode("utf-8"), df, start))
        position += term_size
    return entries


# Recorre un bloque temporal en orden de término, sin cargarlo completo en memoria.
def read_block(path: str) -> Iterator[Tuple[str, List[Posting]]]:
    with open(path, "rb", buffering=READ_BUFFER) as f:
        while header := f.read(BLOCK_ENTRY.size):
            term_size, count = BLOCK_ENTRY.unpack(header)
            term = f.read(term_size).decode("utf-8")
            yield term, decode_postings(f.read(count * POSTING.size))


class SpimiIndex:
    """Índice invertido persistente. El idioma se fija al crearlo y queda en la cabecera."""

    # Abre el archivo si existe o crea uno vacío. Sin `language` usa el del archivo.
    def __init__(self, filepath: str, language: Optional[str] = None, *, block_size: int = DEFAULT_BLOCK_SIZE):
        if language is not None and language not in IDIOMAS:
            raise ValueError(f"Idioma no soportado: {language}")
        if block_size <= 0:
            raise ValueError("block_size debe ser positivo")
        self.block_size = block_size
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

    # --- Construcción -------------------------------------------------------------

    # Construye el índice desde cero: bloques, mezcla y limpieza de los temporales.
    def build(self, documents: Iterable[str]) -> None:
        self._reset()
        paths: List[str] = []
        try:
            paths = self._build_blocks(documents)
            self._merge_blocks(paths)
        except Exception:
            self._reset()
            raise
        finally:
            self._remove_blocks(paths)
        self.flush()

    # SPIMI-INVERT: reparte los documentos en bloques ordenados y devuelve sus rutas.
    def _build_blocks(self, documents: Iterable[str]) -> List[str]:
        paths: List[str] = []
        block: Dict[str, List[Posting]] = {}
        size = 0
        doc_id = self.next_doc_id
        try:
            for text in documents:
                for term, tf in Counter(tokens(text, self.language)).items():
                    encoded = len(term.encode("utf-8"))
                    if encoded > MAX_TERM_BYTES:
                        continue
                    if term not in block:
                        block[term] = []
                        size += BLOCK_ENTRY.size + encoded
                    block[term].append((doc_id, tf))
                    size += POSTING.size
                doc_id += 1
                # Se revisa aquí para que un documento nunca quede partido entre bloques.
                if size >= self.block_size:
                    self._write_block(block, paths)
                    block, size = {}, 0
            if block:
                self._write_block(block, paths)
        except Exception:
            self._remove_blocks(paths)
            raise
        self.next_doc_id = doc_id
        return paths

    # Ordena el bloque por término y lo escribe en un archivo temporal.
    def _write_block(self, block: Dict[str, List[Posting]], paths: List[str]) -> None:
        path = f"{self.filepath}.block{len(paths)}.tmp"
        paths.append(path)
        with open(path, "wb") as f:
            for term in sorted(block):
                encoded = term.encode("utf-8")
                f.write(BLOCK_ENTRY.pack(len(encoded), len(block[term])))
                f.write(encoded)
                f.write(encode_postings(block[term]))

    # Mezcla k-way: escribe las postings de corrido y al final agrega el diccionario.
    def _merge_blocks(self, paths: List[str]) -> None:
        readers = [read_block(path) for path in paths]
        dictionary_path = f"{self.filepath}.dictionary.tmp"
        try:
            with open(dictionary_path, "w+b") as dictionary:
                self._fh.seek(self.page_count * PAGE_SIZE)
                self.postings_start = self.page_count
                size = 0
                page: List[bytes] = []
                free = PAGE_SIZE - DICTIONARY_PAGE.size
                # heapq.merge es la cola de prioridad; es estable: empata en orden de bloque.
                for term, entries in groupby(heapq.merge(*readers, key=itemgetter(0)), key=itemgetter(0)):
                    df = 0
                    for _, postings in entries:
                        self._fh.write(encode_postings(postings))
                        df += len(postings)
                    encoded = term.encode("utf-8")
                    entry = DICTIONARY_ENTRY.pack(len(encoded), df, size) + encoded
                    if len(entry) > free:
                        dictionary.write(encode_dictionary_page(page))
                        page, free = [], PAGE_SIZE - DICTIONARY_PAGE.size
                    page.append(entry)
                    free -= len(entry)
                    size += df * POSTING.size
                    self.term_count += 1
                if page:
                    dictionary.write(encode_dictionary_page(page))

                self.postings_pages = pages_for(size)
                self._fh.write(b"\0" * (self.postings_pages * PAGE_SIZE - size))
                self.dictionary_start = self.postings_start + self.postings_pages
                self.dictionary_pages = pages_for(dictionary.tell())
                dictionary.seek(0)
                shutil.copyfileobj(dictionary, self._fh)
                self.page_count = self.dictionary_start + self.dictionary_pages
        finally:
            for reader in readers:
                reader.close()
            self._remove_blocks([dictionary_path])

    # Borra los archivos temporales de los bloques.
    @staticmethod
    def _remove_blocks(paths: Iterable[str]) -> None:
        for path in paths:
            if os.path.exists(path):
                os.remove(path)

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
