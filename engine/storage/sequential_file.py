from __future__ import annotations

import heapq
import math
import os
import threading
from operator import itemgetter
from typing import Any, Dict, Generator, Iterator, List, Optional, Tuple

from engine.storage.heap_file import Page, PAGE_HEADER_SIZE, SLOT_SIZE, DEFAULT_PAGE_SIZE, latched
from engine.storage.record import RID, Schema

# Fracción de espacio desperdiciado (borrados en main + registros en aux)
# a partir de la cual se reorganiza.
WASTE_THRESHOLD = 0.30


class SequentialFile:
    """Archivo secuencial paginado: main ordenado por clave + aux de desborde.

    - Inserción: búsqueda binaria de la página destino y del slot; si la página
      de main está llena, el registro va al final de aux (con un índice en memoria
      de sus claves, así la búsqueda no recorre aux).
    - Eliminación lazy: solo marca el slot; el espacio se recupera al reorganizar.
    - Reorganización: merge de main (ya ordenado) con aux ordenado, escrito en un
      archivo nuevo con fill_factor. Con auto_reorganize=True se dispara antes de
      una inserción cuando needs_reorganization() es verdadero:
        * desperdicio (borrados en main + aux) > 30% de los slots, o
        * aux supera ceil(log2(páginas de main + 1)) páginas, para que la
          búsqueda siga siendo O(log P) lecturas en main + O(log P) en aux.

    Los RIDs NO son estables: insertar en una página de main desplaza slots y
    reorganizar reescribe el archivo. Los índices deben reconstruirse.

    Las operaciones públicas toman un latch del archivo; scan() lo toma por página,
    así que un scan concurrente con una reorganización puede ver ambos estados.
    """

    stable_rids = False

    def __init__(
        self,
        filepath_main: str,
        filepath_aux: str,
        schema_def: List[Tuple[Any, ...]],
        key_field: str,
        page_size: int = DEFAULT_PAGE_SIZE,
        *,
        auto_reorganize: bool = True,
        fill_factor: float = 0.9,
    ):
        self.schema = Schema(schema_def)
        self.key_field = key_field
        self._latch = threading.RLock()
        self.page_size = page_size
        self.auto_reorganize = auto_reorganize
        self.fill_factor = fill_factor

        if self.schema.record_size + SLOT_SIZE > page_size - PAGE_HEADER_SIZE:
            raise ValueError("El registro es demasiado grande para el tamaño de página")
        if key_field not in self.schema.fields:
            raise ValueError(f"key_field '{key_field}' no existe en el schema")
        if not 0 < fill_factor <= 1:
            raise ValueError("fill_factor debe estar en (0, 1]")

        self.filepath_main = filepath_main
        self.filepath_aux = filepath_aux

        self._fh_main = self._open_file(filepath_main)
        self._fh_aux = self._open_file(filepath_aux)

        self.num_pages_main = os.path.getsize(filepath_main) // page_size
        self.num_pages_aux = os.path.getsize(filepath_aux) // page_size
        self.reorganizations = 0

        # _page_bounds: (min, max) de claves activas o None si la página está vacía.
        # _page_max: separador para enrutar; conserva el último máximo conocido
        # cuando la página se vacía, así la búsqueda binaria no se desvía.
        self._page_bounds: List[Optional[Tuple[Any, Any]]] = []
        self._page_max: List[Any] = []
        self._load_metadata()

    # ------------------------------------------------------------------
    # E/S de páginas
    # ------------------------------------------------------------------

    def _open_file(self, filepath: str):
        is_new = not os.path.exists(filepath)
        if os.path.dirname(filepath):
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
        mode = "w+b" if is_new else "r+b"
        return open(filepath, mode)

    def _read_page(self, fh, page_id: int) -> Page:
        fh.seek(page_id * self.page_size)
        buf = fh.read(self.page_size)
        return Page(page_id, self.page_size, buf)

    def _write_page(self, fh, page: Page) -> None:
        fh.seek(page.page_id * self.page_size)
        fh.write(page.buf)
        fh.flush()

    def _read_page_main(self, page_id: int) -> Page:
        return self._read_page(self._fh_main, page_id)

    def _write_page_main(self, page: Page) -> None:
        self._write_page(self._fh_main, page)

    def _read_page_aux(self, page_id: int) -> Page:
        return self._read_page(self._fh_aux, page_id)

    def _write_page_aux(self, page: Page) -> None:
        self._write_page(self._fh_aux, page)

    def _create_page_main(self) -> Page:
        page = Page(self.num_pages_main, self.page_size)
        self.num_pages_main += 1
        self._write_page_main(page)
        self._page_bounds.append(None)
        self._page_max.append(None)
        return page

    def _create_page_aux(self) -> Page:
        page = Page(self.num_pages_aux, self.page_size)
        self.num_pages_aux += 1
        self._write_page_aux(page)
        return page

    # ------------------------------------------------------------------
    # Metadatos en memoria
    # ------------------------------------------------------------------

    def _record_key(self, data: bytes) -> Any:
        return self.schema.deserialize(data)[self.key_field]

    def _page_key_bounds(self, page: Page) -> Optional[Tuple[Any, Any]]:
        keys = [self._record_key(data) for _, data in page.iter_active()]
        if not keys:
            return None
        return (min(keys), max(keys))

    def _set_bounds(self, page_id: int, bounds: Optional[Tuple[Any, Any]]) -> None:
        self._page_bounds[page_id] = bounds
        if bounds is not None:
            self._page_max[page_id] = bounds[1]

    def _load_metadata(self) -> None:
        """Recorre ambos archivos una vez: límites de página y contadores."""
        self._page_bounds = []
        self._page_max = []
        self._active_main = 0
        self._deleted_main = 0
        for page_id in range(self.num_pages_main):
            page = self._read_page_main(page_id)
            bounds = self._page_key_bounds(page)
            self._page_bounds.append(bounds)
            self._page_max.append(bounds[1] if bounds else None)
            for slot_id in range(page.num_slots):
                if page._read_slot(slot_id)[2]:
                    self._deleted_main += 1
                else:
                    self._active_main += 1
        # Una página vacía hereda el separador anterior: sigue siendo un
        # límite válido para enrutar y mantiene _page_max monótono.
        previous = None
        for page_id, value in enumerate(self._page_max):
            if value is None:
                self._page_max[page_id] = previous
            previous = self._page_max[page_id]
        # Índice en memoria de las claves que están en aux (aux está acotado):
        # buscar una clave no exige recorrer aux.
        self._aux_index = {}
        self._active_aux = 0
        for rid, data in self._iter_aux():
            self._aux_index.setdefault(self._record_key(data), []).append(rid)
            self._active_aux += 1

    def _rebuild_page_bounds(self) -> None:
        self._load_metadata()

    @property
    def aux_page_limit(self) -> int:
        return max(1, math.ceil(math.log2(self.num_pages_main + 1)))

    # ------------------------------------------------------------------
    # Búsqueda de posiciones
    # ------------------------------------------------------------------

    def _locate_page_for_key(self, key: Any) -> int:
        """Primera página cuyo separador es >= key; la última si ninguna."""
        if self.num_pages_main == 0:
            return -1
        lo, hi = 0, self.num_pages_main - 1
        while lo < hi:
            mid = (lo + hi) // 2
            max_key = self._page_max[mid]
            if max_key is None or key <= max_key:
                hi = mid
            else:
                lo = mid + 1
        return lo

    def _slot_key(self, page: Page, slot_id: int) -> Any:
        offset, length, _ = page._read_slot(slot_id)
        return self._record_key(bytes(page.buf[offset: offset + length]))

    def _find_insert_position_in_page(self, page: Page, key: Any) -> int:
        """Lower bound sobre todos los slots (los borrados conservan su clave)."""
        lo, hi = 0, page.num_slots
        while lo < hi:
            mid = (lo + hi) // 2
            if self._slot_key(page, mid) < key:
                lo = mid + 1
            else:
                hi = mid
        return lo

    # ------------------------------------------------------------------
    # Operaciones
    # ------------------------------------------------------------------

    def _insert_into_aux(self, data: bytes) -> RID:
        # aux solo crece al final; sus huecos se recuperan al reorganizar.
        page = None
        if self.num_pages_aux > 0:
            page = self._read_page_aux(self.num_pages_aux - 1)
            slot_id = page.insert_record(data)
            if slot_id is None:
                page = None
        if page is None:
            page = self._create_page_aux()
            slot_id = page.insert_record(data)
        self._write_page_aux(page)
        self._active_aux += 1
        rid = RID(page.page_id, slot_id, file="aux")
        self._aux_index.setdefault(self._record_key(data), []).append(rid)
        return rid

    @latched
    def insert(self, record: Dict[str, Any]) -> RID:
        # La reorganización ocurre ANTES de insertar para que el RID devuelto
        # siga siendo válido al retornar.
        if self.auto_reorganize and self.needs_reorganization():
            self.reorganize()

        data = self.schema.serialize(record)
        key = self.schema.deserialize(data)[self.key_field]

        if self.num_pages_main == 0:
            page = self._create_page_main()
            slot_id = page.insert_sorted_at(data, 0, self.schema.record_size)
            self._write_page_main(page)
            self._set_bounds(page.page_id, (key, key))
            self._active_main += 1
            return RID(page.page_id, slot_id, file="main")

        target_page_id = self._locate_page_for_key(key)
        page = self._read_page_main(target_page_id)
        position = self._find_insert_position_in_page(page, key)
        slot_id = page.insert_sorted_at(data, position, self.schema.record_size)

        if slot_id is not None:
            self._write_page_main(page)
            bounds = self._page_bounds[target_page_id]
            self._set_bounds(target_page_id, (key, key) if bounds is None
                             else (min(bounds[0], key), max(bounds[1], key)))
            self._active_main += 1
            return RID(target_page_id, slot_id, file="main")

        return self._insert_into_aux(data)

    @latched
    def get(self, rid: RID) -> Optional[Dict[str, Any]]:
        if rid.file == "main":
            if rid.page_id < 0 or rid.page_id >= self.num_pages_main:
                return None
            page = self._read_page_main(rid.page_id)
        elif rid.file == "aux":
            if rid.page_id < 0 or rid.page_id >= self.num_pages_aux:
                return None
            page = self._read_page_aux(rid.page_id)
        else:
            return None

        data = page.get_record(rid.slot_id)
        if data is None:
            return None
        return self.schema.deserialize(data)

    @latched
    def delete(self, rid: RID) -> bool:
        """Eliminación lazy. Nunca reorganiza, así los RIDs de un lote siguen válidos."""
        if rid.file == "main":
            if rid.page_id < 0 or rid.page_id >= self.num_pages_main:
                return False
            page = self._read_page_main(rid.page_id)
            ok = page.delete_record(rid.slot_id)
            if ok:
                self._write_page_main(page)
                self._set_bounds(rid.page_id, self._page_key_bounds(page))
                self._active_main -= 1
                self._deleted_main += 1
            return ok
        elif rid.file == "aux":
            if rid.page_id < 0 or rid.page_id >= self.num_pages_aux:
                return False
            page = self._read_page_aux(rid.page_id)
            data = page.get_record(rid.slot_id)
            ok = page.delete_record(rid.slot_id)
            if ok:
                self._write_page_aux(page)
                self._active_aux -= 1
                key = self._record_key(data)
                rids = self._aux_index.get(key, [])
                if rid in rids:
                    rids.remove(rid)
                if not rids:
                    self._aux_index.pop(key, None)
            return ok
        return False

    def _iter_main_from(self, key: Any) -> Iterator[Tuple[RID, Any, bytes]]:
        """(rid, clave, datos) activos de main en orden, desde el lower bound de key
        (desde el principio si key es None)."""
        if self.num_pages_main == 0:
            return
        if key is None:
            page_id, slot_id = 0, 0
            page = self._read_page_main(0)
        else:
            page_id = self._locate_page_for_key(key)
            page = self._read_page_main(page_id)
            slot_id = self._find_insert_position_in_page(page, key)
        while page_id < self.num_pages_main:
            if slot_id == 0 and page.page_id != page_id:
                page = self._read_page_main(page_id)
            for slot in range(slot_id, page.num_slots):
                offset, length, is_deleted = page._read_slot(slot)
                if not is_deleted:
                    data = bytes(page.buf[offset: offset + length])
                    yield RID(page_id, slot, "main"), self._record_key(data), data
            page_id += 1
            slot_id = 0

    def _iter_aux(self) -> Iterator[Tuple[RID, bytes]]:
        for page_id in range(self.num_pages_aux):
            page = self._read_page_aux(page_id)
            for slot_id, data in page.iter_active():
                yield RID(page_id, slot_id, "aux"), data

    @latched
    def search_by_key(self, value: Any) -> List[Tuple[RID, Dict[str, Any]]]:
        """Todos los registros con clave == value.

        O(log P) lecturas en main (búsqueda binaria de página y de slot) más una
        lectura por coincidencia en aux, gracias al índice en memoria de aux.
        """
        results = []
        for rid, key, data in self._iter_main_from(value):
            if key != value:
                break
            results.append((rid, self.schema.deserialize(data)))
        for rid in self._aux_index.get(value, ()):
            data = self._read_page_aux(rid.page_id).get_record(rid.slot_id)
            if data is not None:
                results.append((rid, self.schema.deserialize(data)))
        return results

    @latched
    def range_search(self, lower: Any = None, upper: Any = None, *, include_lower: bool = True,
                     include_upper: bool = True) -> List[Tuple[RID, Dict[str, Any]]]:
        """Registros con lower <(=) clave <(=) upper ordenados por clave; None = sin límite."""
        if lower is not None and upper is not None and lower > upper:
            return []

        def above_lower(key):
            return lower is None or key > lower or (include_lower and key == lower)

        def below_upper(key):
            return upper is None or key < upper or (include_upper and key == upper)

        main = []
        for rid, key, data in self._iter_main_from(lower):
            if not below_upper(key):
                break
            if above_lower(key):
                main.append((key, rid, data))
        aux = sorted(((self._record_key(data), rid, data) for rid, data in self._iter_aux()
                      if above_lower(self._record_key(data)) and below_upper(self._record_key(data))),
                     key=itemgetter(0))
        return [(rid, self.schema.deserialize(data))
                for _, rid, data in heapq.merge(main, aux, key=itemgetter(0))]

    def primary_index_info(self, name: str):
        """Metadatos para que el optimizador use la búsqueda binaria del archivo."""
        from engine.query.planner import IndexInfo
        return IndexInfo(name, self.key_field, SequentialKeyIndex(self), ordered=True, clustered=True)

    def scan(self) -> Generator[Tuple[RID, Dict[str, Any]], None, None]:
        """Recorre activos de main y luego aux, con sus RIDs físicos actuales.

        El recorrido no garantiza orden global. No modificar el archivo durante
        el scan; inserciones y reorganizaciones pueden invalidar RIDs anteriores.
        """
        for file in ("main", "aux"):
            page_id = 0
            while True:
                with self._latch:
                    fh, num_pages = ((self._fh_main, self.num_pages_main) if file == "main"
                                     else (self._fh_aux, self.num_pages_aux))
                    if page_id >= num_pages:
                        break
                    page = self._read_page(fh, page_id)
                for slot_id, data in page.iter_active():
                    yield RID(page_id, slot_id, file), self.schema.deserialize(data)
                page_id += 1

    # ------------------------------------------------------------------
    # Reorganización
    # ------------------------------------------------------------------

    @latched
    def needs_reorganization(self) -> bool:
        total = self._active_main + self._deleted_main + self._active_aux
        if total == 0:
            return False
        wasted = (self._deleted_main + self._active_aux) / total
        return wasted > WASTE_THRESHOLD or self.num_pages_aux > self.aux_page_limit

    @latched
    def reorganize(self, fill_factor: Optional[float] = None) -> None:
        """Merge de main (ordenado) con aux ordenado hacia un archivo nuevo.

        main se recorre en streaming; solo aux se ordena en memoria (está acotado
        por needs_reorganization). El archivo nuevo reemplaza a main al terminar.
        """
        fill_factor = self.fill_factor if fill_factor is None else fill_factor
        record_size = self.schema.record_size
        max_capacity = (self.page_size - PAGE_HEADER_SIZE) // (record_size + SLOT_SIZE)
        capacity_per_page = max(1, int(max_capacity * fill_factor))

        main_sorted = ((key, data) for _, key, data in self._iter_main_all())
        aux_sorted = sorted(((self._record_key(data), data) for _, data in self._iter_aux()),
                            key=itemgetter(0))

        tmp_path = self.filepath_main + ".reorg"
        bounds: List[Optional[Tuple[Any, Any]]] = []
        active = 0
        with open(tmp_path, "w+b") as out:
            page = None
            for key, data in heapq.merge(main_sorted, aux_sorted, key=itemgetter(0)):
                if page is None or page.num_slots >= capacity_per_page:
                    if page is not None:
                        self._write_page(out, page)
                    page = Page(len(bounds), self.page_size)
                    bounds.append((key, key))
                page.insert_sorted_at(data, page.num_slots, record_size)
                bounds[-1] = (bounds[-1][0], key)
                active += 1
            if page is not None:
                self._write_page(out, page)
            out.flush()
            os.fsync(out.fileno())

        self._fh_main.close()
        os.replace(tmp_path, self.filepath_main)
        self._fh_main = open(self.filepath_main, "r+b")
        self._fh_aux.truncate(0)
        self._fh_aux.seek(0)

        self.num_pages_main = len(bounds)
        self.num_pages_aux = 0
        self._page_bounds = bounds
        self._page_max = [upper for _, upper in bounds]
        self._active_main = active
        self._deleted_main = 0
        self._active_aux = 0
        self._aux_index = {}
        self.reorganizations += 1

    def _iter_main_all(self) -> Iterator[Tuple[RID, Any, bytes]]:
        for page_id in range(self.num_pages_main):
            page = self._read_page_main(page_id)
            for slot_id, data in page.iter_active():
                yield RID(page_id, slot_id, "main"), self._record_key(data), data

    @latched
    def stats(self) -> Dict[str, Any]:
        return {
            "num_pages_main": self.num_pages_main,
            "num_pages_aux": self.num_pages_aux,
            "active_main": self._active_main,
            "deleted_main": self._deleted_main,
            "active_aux": self._active_aux,
            "reorganizations": self.reorganizations,
            "disk_bytes": (self.num_pages_main + self.num_pages_aux) * self.page_size,
        }

    @latched
    def close(self) -> None:
        self._fh_main.close()
        self._fh_aux.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


class SequentialKeyIndex:
    """Vista de índice sobre la clave de ordenamiento del archivo secuencial.

    No ocupa espacio: igualdad y rangos usan la búsqueda binaria sobre main (más
    el aux acotado) y el orden se obtiene con un merge de main y aux. Los RIDs se
    calculan en cada consulta, así que no envejecen cuando el archivo se
    reorganiza.
    """

    self_maintained = True  # se actualiza junto con la tabla; nunca se reconstruye

    def __init__(self, storage: SequentialFile):
        self.storage = storage

    def search(self, key) -> List[RID]:
        try:
            return [rid for rid, _ in self.storage.search_by_key(key)]
        except TypeError:  # tipo incomparable con las claves
            return []

    def range_search(self, lower=None, upper=None, *, include_lower=True, include_upper=True) -> List[RID]:
        return [rid for rid, _ in self.storage.range_search(
            lower, upper, include_lower=include_lower, include_upper=include_upper)]

    def iter_ordered(self, reverse: bool = False):
        rids = [rid for rid, _ in self.storage.range_search()]
        return reversed(rids) if reverse else iter(rids)

    def bulk_load_from_storage(self, storage, key_field, *, replace=True) -> int:
        return 0

    def close(self) -> None:
        pass

