"""Tabla organizada como B+ agrupado (index-organized table).

Los registros completos viven en las hojas del B+, ordenados por una clave
única (clave primaria). Expone la misma interfaz de storage que HeapFile y
SequentialFile (insert/get/delete/scan) para registrarse en el Catalog, y un
índice primario que el optimizador usa para igualdad, rangos y ORDER BY.

SQL: CREATE TABLE t (...) USING BTREE  -> la primera columna es la clave.

RIDs: (página de la hoja, posición en la hoja). NO son estables: un split o un
merge mueve registros entre hojas, igual que en el SequentialFile. Por eso los
consumidores relocalizan por clave (search_by_key).
"""

from __future__ import annotations

import threading
from typing import Any, Dict, Iterator, List, Optional, Tuple

from engine.indexes.bplus_tree import CHILD_SIZE, EMPTY_CHILD, NODE_HEADER_SIZE
from engine.indexes.bplus_tree_clustered import BPlusTreeClustered
from engine.storage.heap_file import latched
from engine.storage.record import RID, Schema


def max_clustered_order(schema_def, key_field: str, page_size: int) -> int:
    """Mayor M tal que una hoja (clave + registro) y un nodo interno caben en la página."""
    schema = Schema(schema_def)
    key_size = schema.sizes[schema.fields.index(key_field)]
    leaf = (page_size - NODE_HEADER_SIZE) // (key_size + schema.record_size)
    internal = (page_size - NODE_HEADER_SIZE - CHILD_SIZE) // (CHILD_SIZE + key_size)
    order = min(leaf, internal)
    if order < 2:
        raise ValueError("El registro es demasiado grande para un B+ agrupado con esta página")
    return order


class DuplicateKeyError(ValueError):
    """La clave primaria ya existe en la tabla."""


class ClusteredBPlusFile:
    """Storage cuyo archivo es un B+ agrupado."""

    def __init__(self, filepath: str, schema_def, key_field: str, *, page_size: int = 4096,
                 order: Optional[int] = None):
        self.filepath = filepath
        self.key_field = key_field
        self._latch = threading.RLock()
        self.tree = BPlusTreeClustered(
            filepath, schema_def, key_field,
            M=order or max_clustered_order(schema_def, key_field, page_size), page_size=page_size)
        self.schema = self.tree.schema
        self.page_size = self.tree.header.page_size
        self.primary_index = PrimaryClusteredIndex(self)

    @property
    def num_pages(self) -> int:
        return self.tree.header.number_pages

    def primary_index_info(self, name: str):
        """Metadatos para registrar la clave como índice agrupado en el Catalog."""
        from engine.query.planner import IndexInfo
        return IndexInfo(name, self.key_field, self.primary_index, ordered=True, clustered=True)

    # --- Interfaz de storage ---

    @latched
    def insert(self, record: Dict[str, Any]) -> RID:
        key = record[self.key_field]
        if not self.tree.insert(record):
            raise DuplicateKeyError(f"Clave primaria duplicada: {self.key_field} = {key!r}")
        return self._rid_of(key)

    @latched
    def get(self, rid: RID) -> Optional[Dict[str, Any]]:
        if rid.file != "main" or not 1 <= rid.page_id < self.tree.header.number_pages:
            return None
        node = self.tree._read_node(rid.page_id)
        if not node.isLeaf or not 0 <= rid.slot_id < node.fullness:
            return None
        return dict(node.childs[rid.slot_id])

    @latched
    def delete(self, rid: RID) -> bool:
        record = self.get(rid)
        if record is None:
            return False
        return self.tree.delete(record[self.key_field])

    def scan(self) -> Iterator[Tuple[RID, Dict[str, Any]]]:
        """Recorre las hojas en orden de clave (el latch se toma por hoja)."""
        for rid, _, record in self._entries():
            yield rid, record

    @latched
    def search_by_key(self, value: Any) -> List[Tuple[RID, Dict[str, Any]]]:
        try:
            key = self.tree._normalize_key(value)
        except (TypeError, ValueError, OverflowError):
            return []
        match = self.tree._matching_path(key)
        if match is None:
            return []
        path, index = match
        return [(RID(path[-1][0], index), dict(path[-1][1].childs[index]))]

    def range_search(self, lower: Any = None, upper: Any = None, *, include_lower: bool = True,
                     include_upper: bool = True) -> List[Tuple[RID, Dict[str, Any]]]:
        return [(rid, record) for rid, _, record in
                self._entries(lower, upper, include_lower, include_upper)]

    @latched
    def close(self) -> None:
        self.tree.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    # --- Internos ---

    def _rid_of(self, key) -> RID:
        path, index = self.tree._matching_path(self.tree._normalize_key(key))
        return RID(path[-1][0], index)

    def _entries(self, lower=None, upper=None, include_lower=True, include_upper=True):
        """(rid, clave, registro) en orden, recorriendo la lista enlazada de hojas."""
        with self._latch:
            lower = self.tree._normalize_key(lower) if lower is not None else None
            upper = self.tree._normalize_key(upper) if upper is not None else None
            if lower is not None and upper is not None and lower > upper:
                return
            pos = self.tree._leftmost_leaf_pos() if lower is None else self.tree._find_leaf_pos(lower)
        while pos != EMPTY_CHILD:
            with self._latch:
                if not 1 <= pos < self.tree.header.number_pages:
                    return
                leaf = self.tree._read_node(pos)
            for slot, (key, record) in enumerate(zip(leaf.keys, leaf.childs[:leaf.fullness])):
                if lower is not None and (key < lower or key == lower and not include_lower):
                    continue
                if upper is not None and (key > upper or key == upper and not include_upper):
                    return
                yield RID(pos, slot), key, dict(record)
            pos = leaf.nextLeaf


class PrimaryClusteredIndex:
    """Vista de índice sobre la propia tabla agrupada (no ocupa espacio extra)."""

    def __init__(self, table: ClusteredBPlusFile):
        self.table = table

    def search(self, key) -> List[RID]:
        return [rid for rid, _ in self.table.search_by_key(key)]

    def range_search(self, lower=None, upper=None, *, include_lower=True, include_upper=True) -> List[RID]:
        return [rid for rid, _ in self.table.range_search(
            lower, upper, include_lower=include_lower, include_upper=include_upper)]

    def iter_ordered(self, reverse: bool = False):
        rids = [rid for rid, _ in self.table.scan()]
        return reversed(rids) if reverse else iter(rids)

    def bulk_load_from_storage(self, storage, key_field, *, replace=True) -> int:
        # El índice ES la tabla: no hay nada que reconstruir.
        return 0

    def close(self) -> None:
        pass
