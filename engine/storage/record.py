from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from engine.spatial.geometry import Point

_TYPE_FORMATS = {
    "int": "q",     # 8 bytes, entero con signo
    "float": "d",   # 8 bytes, double
}
TEXT_REFERENCE = struct.Struct(">qi")  # posición y largo del texto en su TextStore
MEDIA_TYPES = ("image", "audio")  # ruta del archivo + vector, en su MediaStore


@dataclass(frozen=True)
class RID:
    page_id: int
    slot_id: int
    file: str = "main"  # "main" o "aux" -> para SequentialFile. HeapFile usa el default.

    def __str__(self) -> str:
        return f"RID(file={self.file}, page={self.page_id}, slot={self.slot_id})"


class Schema:
    def __init__(self, schema_def: List[Tuple[Any, ...]]):
        self.fields: List[str] = []
        self.types: List[str] = []
        self.sizes: List[int] = []
        self.text_stores: Dict[str, Any] = {}
        self.media_stores: Dict[str, Any] = {}
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
            elif ftype == "point":
                fmt_parts.append("16s")
                self.sizes.append(16)
            elif ftype == "text":
                self.text_stores[name] = entry[2]
                fmt_parts.append(f"{TEXT_REFERENCE.size}s")
                self.sizes.append(TEXT_REFERENCE.size)
            elif ftype in MEDIA_TYPES:
                self.media_stores[name] = entry[2]
                fmt_parts.append(f"{TEXT_REFERENCE.size}s")
                self.sizes.append(TEXT_REFERENCE.size)
            else:
                raise ValueError(f"Tipo no soportado: {ftype}")

        self.struct_format = "".join(fmt_parts)
        self.record_size = struct.calcsize(self.struct_format)

    def serialize(self, record: Dict[str, Any]) -> bytes:
        values = []
        for name, ftype, size in zip(self.fields, self.types, self.sizes):
            value = record.get(name)
            if value is None:
                raise ValueError(f"Falta el campo {name!r}: el storage no admite NULL")
            if ftype == "str":
                encoded = str(value).encode("utf-8")
                if len(encoded) > size:
                    # Cortar por bytes puede partir un carácter multibyte (ñ, á, ...)
                    # y el registro ya no se podría leer: se corta en el último
                    # carácter completo.
                    encoded = encoded[:size].decode("utf-8", "ignore").encode("utf-8")
                values.append(encoded.ljust(size, b"\x00"))
            elif ftype == "int":
                values.append(int(value))
            elif ftype == "float":
                values.append(float(value))
            elif ftype == "point":
                if not isinstance(value, Point):
                    raise ValueError(f"El campo {name!r} requiere POINT")
                values.append(struct.pack(">dd", value.lat, value.lon))
            elif ftype == "text":
                values.append(TEXT_REFERENCE.pack(*self.text_stores[name].put(str(value))))
            elif ftype in MEDIA_TYPES:
                if not isinstance(value, str) or not value:
                    raise ValueError(f"El campo {name!r} requiere la ruta de un archivo")
                values.append(TEXT_REFERENCE.pack(*self.media_stores[name].put(ftype, value)))
        return struct.pack(self.struct_format, *values)

    def vector(self, name: str, path: str):
        """Vector extraído al insertar la ruta `path` en la columna multimedia `name`."""
        return self.media_stores[name].vector(self.types[self.fields.index(name)], path)

    def deserialize(self, data: bytes) -> Dict[str, Any]:
        raw_values = struct.unpack(self.struct_format, data)
        record = {}
        for name, ftype, raw in zip(self.fields, self.types, raw_values):
            if ftype == "str":
                record[name] = raw.rstrip(b"\x00").decode("utf-8")
            elif ftype == "point":
                record[name] = Point(*struct.unpack(">dd", raw))
            elif ftype == "text":
                record[name] = self.text_stores[name].get(*TEXT_REFERENCE.unpack(raw))
            elif ftype in MEDIA_TYPES:
                record[name] = self.media_stores[name].get(*TEXT_REFERENCE.unpack(raw))
            else:
                record[name] = raw
        return record
