from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

_TYPE_FORMATS = {
    "int": "q",     # 8 bytes, entero con signo
    "float": "d",   # 8 bytes, double
}


@dataclass(frozen=True)
class RID:
    page_id: int
    slot_id: int

    def __str__(self) -> str:
        return f"RID(page={self.page_id}, slot={self.slot_id})"


class Schema:
    def __init__(self, schema_def: List[Tuple[Any, ...]]):
        self.fields: List[str] = []
        self.types: List[str] = []
        self.sizes: List[int] = []
        fmt_parts = [">"]

        for entry in schema_def:
            name, ftype = entry[0], entry[1]
            self.fields.append(name)
            self.types.append(ftype)

            if ftype == "str":
                size = entry[2]
                self.sizes.append(size)
                fmt_parts.append(f"{size}s")
            elif ftype in _TYPE_FORMATS:
                fmt_parts.append(_TYPE_FORMATS[ftype])
                self.sizes.append(struct.calcsize(_TYPE_FORMATS[ftype]))
            else:
                raise ValueError(f"Tipo no soportado: {ftype}")

        self.struct_format = "".join(fmt_parts)
        self.record_size = struct.calcsize(self.struct_format)

    def serialize(self, record: Dict[str, Any]) -> bytes:
        values = []
        for name, ftype, size in zip(self.fields, self.types, self.sizes):
            value = record.get(name)
            if ftype == "str":
                encoded = str(value).encode("utf-8")[:size]
                encoded = encoded.ljust(size, b"\x00")
                values.append(encoded)
            elif ftype == "int":
                values.append(int(value))
            elif ftype == "float":
                values.append(float(value))
        return struct.pack(self.struct_format, *values)

    def deserialize(self, data: bytes) -> Dict[str, Any]:
        raw_values = struct.unpack(self.struct_format, data)
        record = {}
        for name, ftype, raw in zip(self.fields, self.types, raw_values):
            if ftype == "str":
                record[name] = raw.rstrip(b"\x00").decode("utf-8")
            else:
                record[name] = raw
        return record
