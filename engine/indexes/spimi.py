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

La tabla de documentos guarda por doc_id su RID, longitud y norma, en registros de tamaño
fijo. La norma sigue el esquema lnc.ltc: el documento usa 1 + log10(tf), sin idf (clase 07,
diapositiva 68), así que solo depende del documento y no cambia al modificar la colección.
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
from typing import Dict, Iterable, Iterator, List, NamedTuple, Optional, Tuple

from engine.indexes.rtree import RID_FILES
from engine.storage.record import RID
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
DOCUMENT = struct.Struct(">IHBBId")  # RID (página, slot, archivo), borrado, longitud, norma

DOCUMENTS_PER_PAGE = PAGE_SIZE // DOCUMENT.size  # 204

DEFAULT_BLOCK_SIZE = 8 * 1024 * 1024  # tamaño del bloque en disco; en memoria ocupa más
READ_BUFFER = 16 * PAGE_SIZE  # buffer de lectura de cada bloque durante la mezcla
MAX_TERM_BYTES = 255  # un token más largo no es una palabra (hashes, base64)

Posting = Tuple[int, int]


class DocumentInfo(NamedTuple):
    rid: RID
    length: int
    norm: float


# Convierte una lista de postings en bytes para escribirla en disco.
def encode_postings(postings: Iterable[Posting]) -> bytes:
    return b"".join(POSTING.pack(doc_id, tf) for doc_id, tf in postings)


# Convierte los bytes de una lista en sus postings.
def decode_postings(data: bytes) -> List[Posting]:
    return list(POSTING.iter_unpack(data))


# Calcula cuántas páginas hacen falta para guardar `size` bytes.
def pages_for(size: int) -> int:
    return math.ceil(size / PAGE_SIZE)


# Peso logarítmico de un término en un documento (tf > 0).
def tf_weight(tf: int) -> float:
    return 1 + math.log10(tf)


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
    def build(self, documents: Iterable[Tuple[str, RID]]) -> None:
        self._reset()
        paths: List[str] = []
        try:
            paths = self._build_blocks(documents)
            self._merge_blocks(paths)
            self._copy_documents()
        except Exception:
            self._reset()
            raise
        finally:
            self._remove_blocks(paths + [self._documents_path])
        self.flush()

    # SPIMI-INVERT: reparte los documentos en bloques ordenados y devuelve sus rutas.
    # De paso escribe cada registro de la tabla de documentos en un archivo temporal.
    def _build_blocks(self, documents: Iterable[Tuple[str, RID]]) -> List[str]:
        paths: List[str] = []
        block: Dict[str, List[Posting]] = {}
        size = total_length = 0
        doc_id = self.next_doc_id
        try:
            with open(self._documents_path, "wb") as table:
                for text, rid in documents:
                    length = 0
                    squares = 0.0
                    for term, tf in Counter(tokens(text, self.language)).items():
                        encoded = len(term.encode("utf-8"))
                        if encoded > MAX_TERM_BYTES:
                            continue
                        if term not in block:
                            block[term] = []
                            size += BLOCK_ENTRY.size + encoded
                        block[term].append((doc_id, tf))
                        size += POSTING.size
                        length += tf
                        squares += tf_weight(tf) ** 2
                    table.write(DOCUMENT.pack(rid.page_id, rid.slot_id, RID_FILES.index(rid.file), 0,
                                              length, math.sqrt(squares)))
                    doc_id += 1
                    if doc_id % DOCUMENTS_PER_PAGE == 0:
                        table.write(b"\0" * (PAGE_SIZE - DOCUMENTS_PER_PAGE * DOCUMENT.size))
                    total_length += length
                    # Se revisa aquí para que un documento nunca quede partido entre bloques.
                    if size >= self.block_size:
                        self._write_block(block, paths)
                        block, size = {}, 0
                if block:
                    self._write_block(block, paths)
        except Exception:
            self._remove_blocks(paths + [self._documents_path])
            raise
        self.doc_count += doc_id - self.next_doc_id
        self.total_length += total_length
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

    # Copia la tabla de documentos al final del índice y completa su última página.
    def _copy_documents(self) -> None:
        self.documents_start = self.page_count
        self._fh.seek(self.documents_start * PAGE_SIZE)
        with open(self._documents_path, "rb") as table:
            shutil.copyfileobj(table, self._fh)
            size = table.tell()
        self.documents_pages = pages_for(size)
        self._fh.write(b"\0" * (self.documents_pages * PAGE_SIZE - size))
        self.page_count += self.documents_pages

    # Borra los archivos temporales de los bloques.
    @staticmethod
    def _remove_blocks(paths: Iterable[str]) -> None:
        for path in paths:
            if os.path.exists(path):
                os.remove(path)

    # --- Documentos ---------------------------------------------------------------

    # Ruta del archivo temporal donde se acumula la tabla de documentos.
    @property
    def _documents_path(self) -> str:
        return f"{self.filepath}.documents.tmp"

    # Longitud promedio de los documentos, para BM25.
    @property
    def average_length(self) -> float:
        return self.total_length / self.doc_count if self.doc_count else 0.0

    # Devuelve el RID, la longitud y la norma de un documento leyendo una sola página.
    def document(self, doc_id: int) -> DocumentInfo:
        if not 0 <= doc_id < self.next_doc_id:
            raise IndexError(f"doc_id fuera de rango: {doc_id}")
        page, slot = divmod(doc_id, DOCUMENTS_PER_PAGE)
        data = self._read_pages(self.documents_start + page)
        page_id, slot_id, file, _, length, norm = DOCUMENT.unpack_from(data, slot * DOCUMENT.size)
        return DocumentInfo(RID(page_id, slot_id, RID_FILES[file]), length, norm)

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
