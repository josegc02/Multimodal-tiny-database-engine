from __future__ import annotations

import os
import struct
from typing import Any, Dict, Generator, List, Optional, Tuple

from engine.storage.record import RID, Schema

PAGE_HEADER_FORMAT = ">HH"          # num_slots, data_end
PAGE_HEADER_SIZE = struct.calcsize(PAGE_HEADER_FORMAT)  # 4 bytes

SLOT_FORMAT = ">HHB"                # offset, length, is_deleted
SLOT_SIZE = struct.calcsize(SLOT_FORMAT)  # 5 bytes

DEFAULT_PAGE_SIZE = 4096


class Page:
    def __init__(self, page_id: int, page_size: int = DEFAULT_PAGE_SIZE, buf: Optional[bytes] = None):
        self.page_id = page_id
        self.page_size = page_size

        if buf is None:
            self.buf = bytearray(page_size)
            self._set_header(num_slots=0, data_end=PAGE_HEADER_SIZE)
        else:
            assert len(buf) == page_size, "Tamaño de página inconsistente"
            self.buf = bytearray(buf)

    def _get_header(self) -> Tuple[int, int]:
        return struct.unpack_from(PAGE_HEADER_FORMAT, self.buf, 0)

    def _set_header(self, num_slots: int, data_end: int) -> None:
        struct.pack_into(PAGE_HEADER_FORMAT, self.buf, 0, num_slots, data_end)

    @property
    def num_slots(self) -> int:
        return self._get_header()[0]

    @property
    def data_end(self) -> int:
        return self._get_header()[1]

    def _slot_offset_in_buf(self, slot_id: int) -> int:
        return self.page_size - (slot_id + 1) * SLOT_SIZE

    def _read_slot(self, slot_id: int) -> Tuple[int, int, int]:
        pos = self._slot_offset_in_buf(slot_id)
        return struct.unpack_from(SLOT_FORMAT, self.buf, pos)

    def _write_slot(self, slot_id: int, offset: int, length: int, is_deleted: int) -> None:
        pos = self._slot_offset_in_buf(slot_id)
        struct.pack_into(SLOT_FORMAT, self.buf, pos, offset, length, is_deleted)

    def free_space(self) -> int:
        num_slots, data_end = self._get_header()
        slot_dir_start = self.page_size - num_slots * SLOT_SIZE
        return slot_dir_start - data_end

    def find_reusable_slot(self, record_len: int) -> Optional[int]:
        for slot_id in range(self.num_slots):
            offset, length, is_deleted = self._read_slot(slot_id)
            if is_deleted and length >= record_len:
                return slot_id
        return None

    def can_fit_new_slot(self, record_len: int) -> bool:
        return self.free_space() >= record_len + SLOT_SIZE

    def insert_record(self, data: bytes) -> Optional[int]:
        record_len = len(data)

        reusable = self.find_reusable_slot(record_len)
        if reusable is not None:
            offset, length, _ = self._read_slot(reusable)
            self.buf[offset: offset + record_len] = data
            self._write_slot(reusable, offset, length, is_deleted=0)
            return reusable

        if not self.can_fit_new_slot(record_len):
            return None

        num_slots, data_end = self._get_header()
        offset = data_end
        self.buf[offset: offset + record_len] = data
        self._write_slot(num_slots, offset, record_len, is_deleted=0)
        self._set_header(num_slots=num_slots + 1, data_end=data_end + record_len)
        return num_slots

    def insert_sorted_at(self, data: bytes, position: int, record_len: int) -> Optional[int]:
        if not self.can_fit_new_slot(record_len):
            return None

        num_slots, data_end = self._get_header()
        offset = data_end
        self.buf[offset: offset + record_len] = data

        for i in range(num_slots - 1, position - 1, -1):
            src_pos = self._slot_offset_in_buf(i)
            dst_pos = self._slot_offset_in_buf(i + 1)
            self.buf[dst_pos: dst_pos + SLOT_SIZE] = self.buf[src_pos: src_pos + SLOT_SIZE]

        self._write_slot(position, offset, record_len, is_deleted=0)
        self._set_header(num_slots=num_slots + 1, data_end=data_end + record_len)
        return position

    def get_record(self, slot_id: int) -> Optional[bytes]:
        if slot_id >= self.num_slots:
            return None
        offset, length, is_deleted = self._read_slot(slot_id)
        if is_deleted:
            return None
        return bytes(self.buf[offset: offset + length])

    def delete_record(self, slot_id: int) -> bool:
        if slot_id >= self.num_slots:
            return False
        offset, length, is_deleted = self._read_slot(slot_id)
        if is_deleted:
            return False
        self._write_slot(slot_id, offset, length, is_deleted=1)
        return True

    def iter_active(self) -> Generator[Tuple[int, bytes], None, None]:
        for slot_id in range(self.num_slots):
            offset, length, is_deleted = self._read_slot(slot_id)
            if not is_deleted:
                yield slot_id, bytes(self.buf[offset: offset + length])

    def has_deleted_slots(self) -> bool:
        for slot_id in range(self.num_slots):
            _, _, is_deleted = self._read_slot(slot_id)
            if is_deleted:
                return True
        return False


class HeapFile:
    def __init__(self, filepath: str, schema_def: List[Tuple[Any, ...]], page_size: int = DEFAULT_PAGE_SIZE):
        self.filepath = filepath
        self.page_size = page_size
        self.schema = Schema(schema_def)

        if self.schema.record_size + SLOT_SIZE > page_size - PAGE_HEADER_SIZE:
            raise ValueError("El registro es demasiado grande para el tamaño de página")

        is_new = not os.path.exists(filepath)
        if os.path.dirname(filepath):
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
        mode = "w+b" if is_new else "r+b"
        
        self._fh = open(filepath, mode)

        self.num_pages = 0 if is_new else os.path.getsize(filepath) // page_size

        self.free_pages: set = set()
        self._scan_free_pages()

    def _read_page(self, page_id: int) -> Page:
        self._fh.seek(page_id * self.page_size)
        buf = self._fh.read(self.page_size)
        return Page(page_id, self.page_size, buf)

    def _write_page(self, page: Page) -> None:
        self._fh.seek(page.page_id * self.page_size)
        self._fh.write(page.buf)
        self._fh.flush()

    def _scan_free_pages(self) -> None:
        self.free_pages.clear()
        for page_id in range(self.num_pages):
            self._fh.seek(page_id * self.page_size)
            header = self._fh.read(PAGE_HEADER_SIZE)
            if len(header) < PAGE_HEADER_SIZE:
                continue
            num_slots, data_end = struct.unpack(PAGE_HEADER_FORMAT, header)
            slot_dir_start = self.page_size - num_slots * SLOT_SIZE
            free = slot_dir_start - data_end
            record_needs = self.schema.record_size + SLOT_SIZE
            if free >= record_needs or num_slots > 0:
                self.free_pages.add(page_id)

    def _create_page(self) -> Page:
        page = Page(self.num_pages, self.page_size)
        self.num_pages += 1
        self._write_page(page)
        self.free_pages.add(page.page_id)
        return page

    def insert(self, record: Dict[str, Any]) -> RID:
        data = self.schema.serialize(record)

        for page_id in sorted(self.free_pages):
            page = self._read_page(page_id)
            slot_id = page.insert_record(data)
            if slot_id is not None:
                self._write_page(page)
                if page.free_space() < self.schema.record_size + SLOT_SIZE and not page.has_deleted_slots():
                    self.free_pages.discard(page_id)
                return RID(page_id, slot_id)

        page = self._create_page()
        slot_id = page.insert_record(data)
        self._write_page(page)
        return RID(page.page_id, slot_id)

    def get(self, rid: RID) -> Optional[Dict[str, Any]]:
        if rid.page_id >= self.num_pages:
            return None
        page = self._read_page(rid.page_id)
        data = page.get_record(rid.slot_id)
        if data is None:
            return None
        return self.schema.deserialize(data)

    def delete(self, rid: RID) -> bool:
        if rid.page_id >= self.num_pages:
            return False
        page = self._read_page(rid.page_id)
        ok = page.delete_record(rid.slot_id)
        if ok:
            self._write_page(page)
            self.free_pages.add(rid.page_id)
        return ok

    def scan(self) -> Generator[Tuple[RID, Dict[str, Any]], None, None]:
        for page_id in range(self.num_pages):
            page = self._read_page(page_id)
            for slot_id, data in page.iter_active():
                yield RID(page_id, slot_id), self.schema.deserialize(data)

    def search_by_key(self, field: str, value: Any) -> List[Tuple[RID, Dict[str, Any]]]:
        results = []
        for rid, record in self.scan():
            if record.get(field) == value:
                results.append((rid, record))
        return results

    def stats(self) -> Dict[str, Any]:
        active = 0
        deleted = 0
        for page_id in range(self.num_pages):
            page = self._read_page(page_id)
            for slot_id in range(page.num_slots):
                _, _, is_deleted = page._read_slot(slot_id)
                if is_deleted:
                    deleted += 1
                else:
                    active += 1
        return {
            "num_pages": self.num_pages,
            "active_records": active,
            "deleted_slots": deleted,
            "disk_bytes": self.num_pages * self.page_size,
            "record_size": self.schema.record_size,
        }

    def close(self) -> None:
        self._fh.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
