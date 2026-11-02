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

Para leer, el índice guarda en memoria el primer término de cada página del diccionario:
ubica la página con búsqueda binaria y solo lee esa página y la lista del término.

Reescribir el índice en cada cambio sería muy caro, así que se usa un índice auxiliar: las
inserciones van a un delta en memoria y las eliminaciones a un conjunto de borrados, y ambos
se registran en un log para sobrevivir a un reinicio. Cuando los cambios superan un porcentaje
del índice, se consolida en un archivo nuevo. El log lleva la generación del índice: si el
proceso cae entre reemplazar el archivo y borrar el log, ese log se ignora. Hasta consolidar,
df(termino) sigue contando los documentos borrados; postings(termino) ya no los devuelve.
"""

from __future__ import annotations

import bisect
import heapq
import json
import math
import os
import shutil
import struct
from collections import Counter
from dataclasses import dataclass
from itertools import groupby
from operator import itemgetter
from typing import Dict, Iterable, Iterator, List, NamedTuple, Optional, Tuple

from engine.indexes.rtree import _rid, _rid_key
from engine.storage.record import RID
from engine.text.preprocessing import IDIOMAS, tokens

PAGE_SIZE = 4096
MAGIC = b"SPI1"

# magic, idioma, documentos, siguiente doc_id, términos, longitud total, páginas,
# inicio y páginas de: diccionario, postings y documentos; generación
HEADER = struct.Struct(">4s2sIIIQIIIIIIII")
POSTING = struct.Struct(">II")  # doc_id, tf
BLOCK_ENTRY = struct.Struct(">BI")  # bytes del término, postings
DICTIONARY_PAGE = struct.Struct(">H")  # entradas de la página
DICTIONARY_ENTRY = struct.Struct(">BIQ")  # bytes del término, df, byte donde empieza su lista
DOCUMENT = struct.Struct(">IHBId")  # RID (página, slot, archivo), longitud, norma

DOCUMENTS_PER_PAGE = PAGE_SIZE // DOCUMENT.size  # 215

DEFAULT_BLOCK_SIZE = 8 * 1024 * 1024  # tamaño del bloque en disco; en memoria ocupa más
READ_BUFFER = 16 * PAGE_SIZE  # buffer de lectura de cada bloque durante la mezcla
MAX_TERM_BYTES = 255  # un token más largo no es una palabra (hashes, base64)
MERGE_RATIO = 0.1  # se consolida cuando los cambios superan esta fracción de los documentos
MIN_CHANGES = 1000  # mínimo de cambios para consolidar: en tablas pequeñas no compensa

Posting = Tuple[int, int]


class DocumentInfo(NamedTuple):
    rid: RID
    length: int
    norm: float


@dataclass
class SpimiStats:
    """Lecturas acumuladas, para EXPLAIN y los benchmarks. Se reinician con reset_stats()."""
    pages_read: int = 0
    postings_read: int = 0


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


# Norma de coseno de un documento a partir de sus tf.
def document_norm(frequencies: Iterable[int]) -> float:
    return math.sqrt(sum(tf_weight(tf) ** 2 for tf in frequencies))


# Escribe el registro de un documento; las páginas de la tabla no parten registros.
def write_document(table, doc_id: int, document: DocumentInfo) -> None:
    table.write(DOCUMENT.pack(*_rid_key(document.rid), document.length, document.norm))
    if (doc_id + 1) % DOCUMENTS_PER_PAGE == 0:
        table.write(b"\0" * (PAGE_SIZE - DOCUMENTS_PER_PAGE * DOCUMENT.size))


# Lee el registro que está en una posición de una página de la tabla.
def read_document(data: bytes, slot: int) -> DocumentInfo:
    page_id, slot_id, file, length, norm = DOCUMENT.unpack_from(data, slot * DOCUMENT.size)
    return DocumentInfo(_rid((page_id, slot_id, file)), length, norm)


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
    def __init__(self, filepath: str, language: Optional[str] = None, *, block_size: int = DEFAULT_BLOCK_SIZE,
                 merge_ratio: float = MERGE_RATIO, min_changes: int = MIN_CHANGES):
        if language is not None and language not in IDIOMAS:
            raise ValueError(f"Idioma no soportado: {language}")
        if block_size <= 0:
            raise ValueError("block_size debe ser positivo")
        self.block_size = block_size
        self.merge_ratio = merge_ratio
        self.min_changes = min_changes
        self.generation = 0
        self._log_file = None
        self._clear_delta()
        self.stats = SpimiStats()
        self._dictionary_index: Optional[List[str]] = None
        self.filepath = os.fspath(filepath)
        exists = os.path.exists(self.filepath) and os.path.getsize(self.filepath) > 0
        self._fh = open(self.filepath, "r+b" if exists else "w+b")
        try:
            if exists:
                self._read_header()
                if language is not None and language != self.language:
                    raise ValueError("El idioma no coincide con el del archivo")
                self._replay_log()
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
         self.documents_start, self.documents_pages, self.generation) = HEADER.unpack(data)
        self.language = language.decode("ascii")

    # Guarda los totales y la ubicación de cada zona en la página 0. Los cambios del delta
    # no se incluyen en los totales: el log los vuelve a aplicar al abrir.
    def _write_header(self) -> None:
        self._fh.seek(0)
        self._fh.write(HEADER.pack(MAGIC, self.language.encode("ascii"), self.doc_count - self._delta_count,
                                   self.next_doc_id - self._delta_ids, self.term_count,
                                   self.total_length - self._delta_length, self.page_count,
                                   self.dictionary_start, self.dictionary_pages,
                                   self.postings_start, self.postings_pages,
                                   self.documents_start, self.documents_pages,
                                   self.generation).ljust(PAGE_SIZE, b"\0"))

    # Deja el índice vacío: solo queda la cabecera.
    def _reset(self) -> None:
        self._remove_log()
        self._clear_delta()
        self._fh.truncate(0)
        self.doc_count = self.next_doc_id = self.term_count = self.total_length = 0
        self.page_count = 1
        self.dictionary_start = self.dictionary_pages = 0
        self.postings_start = self.postings_pages = 0
        self.documents_start = self.documents_pages = 0
        self._dictionary_index = None
        self._write_header()

    # Lee `count` páginas seguidas con una sola operación de disco.
    def _read_pages(self, start: int, count: int = 1) -> bytes:
        self.stats.pages_read += count
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
                    terms = self.analyze(text)
                    for term, tf in terms.items():
                        if term not in block:
                            block[term] = []
                            size += BLOCK_ENTRY.size + len(term.encode("utf-8"))
                        block[term].append((doc_id, tf))
                        size += POSTING.size
                    length = sum(terms.values())
                    write_document(table, doc_id, DocumentInfo(rid, length, document_norm(terms.values())))
                    doc_id += 1
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

    # Mezcla los bloques temporales y cierra sus archivos aunque falle.
    def _merge_blocks(self, paths: List[str]) -> None:
        readers = [read_block(path) for path in paths]
        try:
            self._merge(readers)
        finally:
            for reader in readers:
                reader.close()

    # Mezcla k-way: escribe las postings de corrido y al final agrega el diccionario.
    def _merge(self, sources: Iterable[Iterable[Tuple[str, List[Posting]]]]) -> None:
        dictionary_path = f"{self.filepath}.dictionary.tmp"
        try:
            with open(dictionary_path, "w+b") as dictionary:
                self._fh.seek(self.page_count * PAGE_SIZE)
                self.postings_start = self.page_count
                size = 0
                page: List[bytes] = []
                free = PAGE_SIZE - DICTIONARY_PAGE.size
                # heapq.merge es la cola de prioridad; es estable: empata en orden de bloque.
                for term, entries in groupby(heapq.merge(*sources, key=itemgetter(0)), key=itemgetter(0)):
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
                self._dictionary_index = None
        finally:
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

    # --- Lectura ------------------------------------------------------------------

    # Pasa un texto por el mismo pipeline de los documentos y devuelve término -> tf.
    def analyze(self, text: Optional[str]) -> Dict[str, int]:
        return {term: tf for term, tf in Counter(tokens(text or "", self.language)).items()
                if len(term.encode("utf-8")) <= MAX_TERM_BYTES}

    # Primer término de cada página del diccionario; se carga en la primera búsqueda.
    def _first_terms(self) -> List[str]:
        if self._dictionary_index is None:
            self._dictionary_index = [decode_dictionary_page(self._read_pages(self.dictionary_start + page))[0][0]
                                      for page in range(self.dictionary_pages)]
        return self._dictionary_index

    # Busca un término ya preprocesado y devuelve su df y su inicio, o None si no existe.
    def _lookup(self, term: str) -> Optional[Tuple[int, int]]:
        page = bisect.bisect_right(self._first_terms(), term) - 1
        if page < 0:
            return None
        for candidate, df, start in decode_dictionary_page(self._read_pages(self.dictionary_start + page)):
            if candidate == term:
                return df, start
        return None

    # Lee una lista de corrido, aunque cruce varias páginas.
    def _read_postings(self, df: int, start: int) -> List[Posting]:
        size = df * POSTING.size
        first, offset = divmod(start, PAGE_SIZE)
        data = self._read_pages(self.postings_start + first, pages_for(offset + size))
        self.stats.postings_read += df
        return decode_postings(data[offset:offset + size])

    # Número de documentos que contienen un término; incluye los borrados sin consolidar.
    def df(self, term: str) -> int:
        entry = self._lookup(term)
        return (entry[0] if entry else 0) + len(self._delta.get(term, ()))

    # Lista de (doc_id, tf) de un término ya preprocesado, ordenada por doc_id y sin borrados.
    def postings(self, term: str) -> List[Posting]:
        entry = self._lookup(term)
        result = self._read_postings(*entry) if entry else []
        delta = self._delta.get(term, ())
        self.stats.postings_read += len(delta)
        result.extend(delta)
        return [posting for posting in result if posting[0] not in self._deleted]

    # Recorre el diccionario del índice principal en orden: (término, df, inicio).
    def terms(self) -> Iterator[Tuple[str, int, int]]:
        for page in range(self.dictionary_pages):
            yield from decode_dictionary_page(self._read_pages(self.dictionary_start + page))

    # Devuelve los RID de los documentos que contienen todos los términos del texto.
    def search(self, text: Optional[str]) -> List[RID]:
        terms = self.analyze(text)
        if not terms:
            return []
        common = set.intersection(*({doc_id for doc_id, _ in self.postings(term)} for term in terms))
        return [self.document(doc_id).rid for doc_id in sorted(common)]

    # Pone en cero los contadores de lecturas.
    def reset_stats(self) -> None:
        self.stats = SpimiStats()

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
        if not 0 <= doc_id < self.next_doc_id or doc_id in self._deleted:
            raise IndexError(f"doc_id fuera de rango: {doc_id}")
        if doc_id in self._delta_documents:
            return self._delta_documents[doc_id]
        page, slot = divmod(doc_id, DOCUMENTS_PER_PAGE)
        return read_document(self._read_pages(self.documents_start + page), slot)

    # Recorre los documentos vivos en orden de doc_id.
    def _live_documents(self) -> Iterator[Tuple[int, DocumentInfo]]:
        main_count = self.next_doc_id - self._delta_ids
        for page in range(self.documents_pages):
            data = self._read_pages(self.documents_start + page)
            first = page * DOCUMENTS_PER_PAGE
            for doc_id in range(first, min(first + DOCUMENTS_PER_PAGE, main_count)):
                if doc_id not in self._deleted:
                    yield doc_id, read_document(data, doc_id - first)
        for doc_id in sorted(self._delta_documents):
            if doc_id not in self._deleted:
                yield doc_id, self._delta_documents[doc_id]

    # Busca el doc_id de un RID. El mapa se arma la primera vez que se elimina algo.
    def _doc_id_of(self, rid: RID) -> Optional[int]:
        if self._doc_ids is None:
            self._doc_ids = {_rid_key(document.rid): doc_id for doc_id, document in self._live_documents()}
        return self._doc_ids.get(_rid_key(rid))

    # --- Mantenimiento ------------------------------------------------------------

    # Ruta del log con los cambios que aún no están en el índice principal.
    @property
    def _log_path(self) -> str:
        return f"{self.filepath}.delta"

    # Deja vacío el estado en memoria de los cambios sin consolidar.
    def _clear_delta(self) -> None:
        self._delta: Dict[str, List[Posting]] = {}
        self._delta_documents: Dict[int, DocumentInfo] = {}
        self._deleted = set()
        self._doc_ids: Optional[Dict[Tuple[int, int, int], int]] = None
        self._delta_count = self._delta_ids = self._delta_length = self._changes = 0

    # Agrega un cambio al log y lo envía al sistema antes de aplicarlo.
    def _append_log(self, change: dict) -> None:
        if self._log_file is None:
            self._log_file = open(self._log_path, "ab")
            if self._log_file.tell() == 0:
                self._log_file.write(json.dumps({"generation": self.generation}).encode("utf-8") + b"\n")
        self._log_file.write(json.dumps(change, ensure_ascii=False).encode("utf-8") + b"\n")
        self._log_file.flush()

    # Cierra y borra el log.
    def _remove_log(self) -> None:
        if self._log_file is not None:
            self._log_file.close()
            self._log_file = None
        self._remove_blocks([self._log_path])

    # Vuelve a aplicar el log al abrir. Si la escritura final quedó cortada, la descarta.
    def _replay_log(self) -> None:
        if not os.path.exists(self._log_path):
            return
        with open(self._log_path, "rb") as log:
            first = log.readline()
            valid = len(first)
            try:
                current = json.loads(first).get("generation") == self.generation
            except ValueError:
                current = False
            if current:
                for line in log:
                    try:
                        change = json.loads(line) if line.endswith(b"\n") else None
                    except ValueError:
                        change = None
                    if change is None:
                        break
                    if change["op"] == "insert":
                        self._apply_insert(change["doc"], _rid(tuple(change["rid"])), change["terms"])
                    else:
                        self._apply_delete(change["doc"])
                    valid += len(line)
        if not current:
            self._remove_log()
        elif valid != os.path.getsize(self._log_path):
            with open(self._log_path, "r+b") as log:
                log.truncate(valid)

    # Registra un documento nuevo en el delta y actualiza los totales.
    def _apply_insert(self, doc_id: int, rid: RID, terms: Dict[str, int]) -> None:
        for term, tf in terms.items():
            self._delta.setdefault(term, []).append((doc_id, tf))
        length = sum(terms.values())
        self._delta_documents[doc_id] = DocumentInfo(rid, length, document_norm(terms.values()))
        if self._doc_ids is not None:
            self._doc_ids[_rid_key(rid)] = doc_id
        self.next_doc_id = doc_id + 1
        self.doc_count += 1
        self.total_length += length
        self._delta_ids += 1
        self._delta_count += 1
        self._delta_length += length
        self._changes += 1

    # Marca un documento como borrado y actualiza los totales.
    def _apply_delete(self, doc_id: int) -> None:
        document = self.document(doc_id)
        self._deleted.add(doc_id)
        if self._doc_ids is not None:
            self._doc_ids.pop(_rid_key(document.rid), None)
        self.doc_count -= 1
        self.total_length -= document.length
        self._delta_count -= 1
        self._delta_length -= document.length
        self._changes += 1

    # Consolida cuando los cambios superan el límite. El límite es proporcional para que
    # el costo total de consolidar crezca de forma lineal con la colección.
    def _maybe_consolidate(self) -> None:
        if self._changes >= max(self.min_changes, self.merge_ratio * self.doc_count):
            self.consolidate()

    # Agrega un documento al índice.
    def insert(self, text: Optional[str], rid: RID) -> None:
        terms = self.analyze(text)
        doc_id = self.next_doc_id
        self._append_log({"op": "insert", "doc": doc_id, "rid": _rid_key(rid), "terms": terms})
        self._apply_insert(doc_id, rid, terms)
        self._maybe_consolidate()

    # Elimina el documento de un RID. Devuelve False si no estaba en el índice.
    def delete(self, text: Optional[str], rid: RID) -> bool:
        doc_id = self._doc_id_of(rid)
        if doc_id is None:
            return False
        self._append_log({"op": "delete", "doc": doc_id})
        self._apply_delete(doc_id)
        self._maybe_consolidate()
        return True

    # Reescribe las listas de una fuente sin borrados y con los doc_id nuevos.
    @staticmethod
    def _renumber(entries: Iterable[Tuple[str, List[Posting]]], new_ids: Dict[int, int]):
        for term, postings in entries:
            postings = [(new_ids[doc_id], tf) for doc_id, tf in postings if doc_id in new_ids]
            if postings:
                yield term, postings

    # Indexa una columna de texto de una tabla y devuelve cuántos documentos agregó.
    def bulk_load_from_storage(self, storage, key_field: str, *, replace: bool = True) -> int:
        if key_field not in storage.schema.fields:
            raise ValueError(f"El campo '{key_field}' no existe en el schema")
        documents = ((record[key_field], rid) for rid, record in storage.scan())
        if replace:
            self.build(documents)
            return self.doc_count
        count = 0
        for text, rid in documents:
            self.insert(text, rid)
            count += 1
        return count

    # Une el índice principal y el delta en un archivo nuevo y reemplaza al anterior.
    # Los doc_id se renumeran en orden, así que el resultado equivale a construir desde cero.
    def consolidate(self) -> None:
        if not self._changes:
            return
        path = f"{self.filepath}.consolidate.tmp"
        self._remove_blocks([path])
        target = SpimiIndex(path, self.language, block_size=self.block_size)
        try:
            new_ids: Dict[int, int] = {}
            with open(target._documents_path, "wb") as table:
                for doc_id, document in self._live_documents():
                    new_ids[doc_id] = len(new_ids)
                    write_document(table, new_ids[doc_id], document)
            target.doc_count = target.next_doc_id = len(new_ids)
            target.total_length = self.total_length
            main = ((term, self._read_postings(df, start)) for term, df, start in self.terms())
            delta = ((term, self._delta[term]) for term in sorted(self._delta))
            target._merge([self._renumber(main, new_ids), self._renumber(delta, new_ids)])
            target._copy_documents()
            target.generation = self.generation + 1
            target.close()
        except Exception:
            target.close()
            self._remove_blocks([path])
            raise
        finally:
            self._remove_blocks([target._documents_path])
        self._fh.close()
        try:
            os.replace(path, self.filepath)
        finally:
            self._fh = open(self.filepath, "r+b")
        self._remove_log()
        self._clear_delta()
        self._dictionary_index = None
        self._read_header()

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
        if self._log_file is not None:
            self._log_file.close()
            self._log_file = None
        if not self._fh.closed:
            self.flush()
            self._fh.close()

    def __enter__(self) -> SpimiIndex:
        return self

    def __exit__(self, *exc) -> None:
        self.close()
