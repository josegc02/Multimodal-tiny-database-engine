from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

from engine.storage.heap_file import Page, PAGE_HEADER_SIZE, SLOT_SIZE, DEFAULT_PAGE_SIZE
from engine.storage.record import RID, Schema


class SequentialFile:
    def __init__(
        self,
        filepath_main: str,
        filepath_aux: str,
        schema_def: List[Tuple[Any, ...]],
        key_field: str,
        page_size: int = DEFAULT_PAGE_SIZE,
    ):
        self.schema = Schema(schema_def)
        self.key_field = key_field
        self.page_size = page_size

        if self.schema.record_size + SLOT_SIZE > page_size - PAGE_HEADER_SIZE:
            raise ValueError("El registro es demasiado grande para el tamaño de página")
        if key_field not in self.schema.fields:
            raise ValueError(f"key_field '{key_field}' no existe en el schema")

        self.filepath_main = filepath_main
        self.filepath_aux = filepath_aux

        self._fh_main = self._open_file(filepath_main)
        self._fh_aux = self._open_file(filepath_aux)

        self.num_pages_main = os.path.getsize(filepath_main) // page_size
        self.num_pages_aux = os.path.getsize(filepath_aux) // page_size

        self._page_bounds: List[Optional[Tuple[Any, Any]]] = []
        self._rebuild_page_bounds()

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
        return page

    def _create_page_aux(self) -> Page:
        page = Page(self.num_pages_aux, self.page_size)
        self.num_pages_aux += 1
        self._write_page_aux(page)
        return page

    def _record_key(self, data: bytes) -> Any:
        record = self.schema.deserialize(data)
        return record[self.key_field]

    def _page_key_bounds(self, page: Page) -> Optional[Tuple[Any, Any]]:
        keys = [self._record_key(data) for _, data in page.iter_active()]
        if not keys:
            return None
        return (min(keys), max(keys))

    def _rebuild_page_bounds(self) -> None:
        self._page_bounds = []
        for page_id in range(self.num_pages_main):
            page = self._read_page_main(page_id)
            self._page_bounds.append(self._page_key_bounds(page))

    def _locate_page_for_key(self, key: Any) -> int:
        if self.num_pages_main == 0:
            return -1

        lo, hi = 0, self.num_pages_main - 1
        while lo < hi:
            mid = (lo + hi) // 2
            bounds = self._page_bounds[mid]
            if bounds is None:
                hi = mid
                continue
            _, max_key = bounds
            if key <= max_key:
                hi = mid
            else:
                lo = mid + 1
        return lo

    def _find_insert_position_in_page(self, page: Page, key: Any) -> int:
        lo, hi = 0, page.num_slots
        while lo < hi:
            mid = (lo + hi) // 2
            offset, length, _ = page._read_slot(mid)
            mid_key = self._record_key(bytes(page.buf[offset: offset + length]))
            if mid_key < key:
                lo = mid + 1
            else:
                hi = mid
        return lo

    def _insert_into_aux(self, data: bytes) -> RID:
        for page_id in range(self.num_pages_aux):
            page = self._read_page_aux(page_id)
            slot_id = page.insert_record(data)
            if slot_id is not None:
                self._write_page_aux(page)
                return RID(page_id, slot_id, file="aux")

        page = self._create_page_aux()
        slot_id = page.insert_record(data)
        self._write_page_aux(page)
        return RID(page.page_id, slot_id, file="aux")

    def insert(self, record: Dict[str, Any]) -> RID:
        data = self.schema.serialize(record)
        key = record[self.key_field]

        if self.num_pages_main == 0:
            page = self._create_page_main()
            slot_id = page.insert_sorted_at(data, 0, self.schema.record_size)
            self._write_page_main(page)
            self._page_bounds[page.page_id] = self._page_key_bounds(page)
            return RID(page.page_id, slot_id, file="main")

        target_page_id = self._locate_page_for_key(key)
        page = self._read_page_main(target_page_id)
        position = self._find_insert_position_in_page(page, key)
        slot_id = page.insert_sorted_at(data, position, self.schema.record_size)

        if slot_id is not None:
            self._write_page_main(page)
            self._page_bounds[target_page_id] = self._page_key_bounds(page)
            return RID(target_page_id, slot_id, file="main")

        return self._insert_into_aux(data)

    def get(self, rid: RID) -> Optional[Dict[str, Any]]:
        raise NotImplementedError("Pendiente: se implementa junto con la búsqueda binaria")

    def delete(self, rid: RID) -> bool:
        if rid.file == "main":
            if rid.page_id < 0 or rid.page_id >= self.num_pages_main:
                return False
            page = self._read_page_main(rid.page_id)
            ok = page.delete_record(rid.slot_id)
            if ok:
                self._write_page_main(page)
                self._page_bounds[rid.page_id] = self._page_key_bounds(page)
            return ok
        elif rid.file == "aux":
            if rid.page_id < 0 or rid.page_id >= self.num_pages_aux:
                return False
            page = self._read_page_aux(rid.page_id)
            ok = page.delete_record(rid.slot_id)
            if ok:
                self._write_page_aux(page)
            return ok
        return False

    def search_by_key(self, value: Any) -> List[Tuple[RID, Dict[str, Any]]]:
        raise NotImplementedError("Pendiente: búsqueda binaria sobre páginas ordenadas")

    def needs_reorganization(self) -> bool:
        deleted_main = 0
        active_main = 0
        for page_id in range(self.num_pages_main):
            page = self._read_page_main(page_id)
            for slot_id in range(page.num_slots):
                _, _, is_deleted = page._read_slot(slot_id)
                if is_deleted:
                    deleted_main += 1
                else:
                    active_main += 1

        aux_count = 0
        for page_id in range(self.num_pages_aux):
            page = self._read_page_aux(page_id)
            aux_count += sum(1 for _ in page.iter_active())

        total = active_main + deleted_main + aux_count
        if total == 0:
            return False

        return (deleted_main + aux_count) / total > 0.30

    def reorganize(self, fill_factor: float = 0.9) -> None:
        all_records: List[bytes] = []
        for page_id in range(self.num_pages_main):
            page = self._read_page_main(page_id)
            for _, data in page.iter_active():
                all_records.append(data)

        for page_id in range(self.num_pages_aux):
            page = self._read_page_aux(page_id)
            for _, data in page.iter_active():
                all_records.append(data)

        all_records.sort(key=lambda d: self._record_key(d))

        self._fh_main.truncate(0)
        self._fh_main.seek(0)
        self.num_pages_main = 0
        self._page_bounds = []

        self._fh_aux.truncate(0)
        self._fh_aux.seek(0)
        self.num_pages_aux = 0

        if not all_records:
            return

        record_size = self.schema.record_size
        max_capacity = (self.page_size - PAGE_HEADER_SIZE) // (record_size + SLOT_SIZE)
        capacity_per_page = max(1, int(max_capacity * fill_factor))

        current_page = self._create_page_main()
        for data in all_records:
            if current_page.num_slots >= capacity_per_page:
                self._write_page_main(current_page)
                self._page_bounds[current_page.page_id] = self._page_key_bounds(current_page)
                current_page = self._create_page_main()

            current_page.insert_sorted_at(data, current_page.num_slots, record_size)

        if current_page.num_slots > 0:
            self._write_page_main(current_page)
            self._page_bounds[current_page.page_id] = self._page_key_bounds(current_page)

    def close(self) -> None:
        self._fh_main.close()
        self._fh_aux.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()