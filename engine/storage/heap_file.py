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
