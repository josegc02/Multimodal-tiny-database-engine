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

    def can_fit_new_slot(self, record_len: int) -> bool:
        return self.free_space() >= record_len + SLOT_SIZE

    def insert_record(self, data: bytes) -> Optional[int]:
        record_len = len(data)
        if not self.can_fit_new_slot(record_len):
            return None

        num_slots, data_end = self._get_header()
        offset = data_end
        self.buf[offset: offset + record_len] = data
        self._write_slot(num_slots, offset, record_len, is_deleted=0)
        self._set_header(num_slots=num_slots + 1, data_end=data_end + record_len)
        return num_slots

    def get_record(self, slot_id: int) -> Optional[bytes]:
        if slot_id >= self.num_slots:
            return None
        offset, length, is_deleted = self._read_slot(slot_id)
        if is_deleted:
            return None
        return bytes(self.buf[offset: offset + length])

    def iter_active(self) -> Generator[Tuple[int, bytes], None, None]:
        for slot_id in range(self.num_slots):
            offset, length, is_deleted = self._read_slot(slot_id)
            if not is_deleted:
                yield slot_id, bytes(self.buf[offset: offset + length])


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

    def _read_page(self, page_id: int) -> Page:
        self._fh.seek(page_id * self.page_size)
        buf = self._fh.read(self.page_size)
        return Page(page_id, self.page_size, buf)

    def _write_page(self, page: Page) -> None:
        self._fh.seek(page.page_id * self.page_size)
        self._fh.write(page.buf)
        self._fh.flush()

    def _create_page(self) -> Page:
        page = Page(self.num_pages, self.page_size)
        self.num_pages += 1
        self._write_page(page)
        return page

    def insert(self, record: Dict[str, Any]) -> RID:
        data = self.schema.serialize(record)

        if self.num_pages > 0:
            last_page = self._read_page(self.num_pages - 1)
            slot_id = last_page.insert_record(data)
            if slot_id is not None:
                self._write_page(last_page)
                return RID(last_page.page_id, slot_id)

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

    def scan(self) -> Generator[Tuple[RID, Dict[str, Any]], None, None]:
        for page_id in range(self.num_pages):
            page = self._read_page(page_id)
            for slot_id, data in page.iter_active():
                yield RID(page_id, slot_id), self.schema.deserialize(data)

    def close(self) -> None:
        self._fh.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
