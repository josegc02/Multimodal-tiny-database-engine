"""Formato binario de los temporales de consultas, serializado con struct.

Cabecera de archivo: magic/version EXT1 (4 bytes). Cada registro contiene un
uint32 con la cantidad de campos. Cada campo guarda nombre UTF-8 (longitud uint32
+ bytes), etiqueta uint8 y valor: NULL (sin payload), int64, float64 o texto UTF-8
con longitud uint32. Todos los números usan big-endian, como storage.record.

Se incluyen nombres y tipos porque estos operadores también reciben iterables
sin Schema y permiten NULL. Los registros del heap conservan su formato original.
"""

import struct
from typing import Any, BinaryIO, Mapping

MAGIC = b"EXT1"
UINT32 = struct.Struct(">I")
TAG = struct.Struct(">B")
INT64 = struct.Struct(">q")
FLOAT64 = struct.Struct(">d")
NULL, INTEGER, FLOAT, TEXT = range(4)


def _read_exact(fh: BinaryIO, size: int) -> bytes:
    data = fh.read(size)
    if len(data) != size:
        raise ValueError("Archivo temporal truncado")
    return data


def write_header(fh: BinaryIO) -> None:
    fh.write(MAGIC)


def read_header(fh: BinaryIO) -> None:
    if _read_exact(fh, len(MAGIC)) != MAGIC:
        raise ValueError("Formato de archivo temporal no soportado")


def _write_text(fh: BinaryIO, text: str) -> None:
    encoded = text.encode("utf-8")
    fh.write(UINT32.pack(len(encoded)))
    fh.write(encoded)


def _read_text(fh: BinaryIO) -> str:
    size = UINT32.unpack(_read_exact(fh, UINT32.size))[0]
    return _read_exact(fh, size).decode("utf-8")


def write_record(fh: BinaryIO, row: Mapping[str, Any]) -> None:
    fh.write(UINT32.pack(len(row)))
    for name, value in row.items():
        if not isinstance(name, str):
            raise TypeError("Los nombres de campo deben ser strings")
        _write_text(fh, name)
        if value is None:
            fh.write(TAG.pack(NULL))
        elif type(value) is int:
            if not -(1 << 63) <= value < (1 << 63):
                raise ValueError("El entero no cabe en int64")
            fh.write(TAG.pack(INTEGER))
            fh.write(INT64.pack(value))
        elif type(value) is float:
            fh.write(TAG.pack(FLOAT))
            fh.write(FLOAT64.pack(value))
        elif type(value) is str:
            fh.write(TAG.pack(TEXT))
            _write_text(fh, value)
        else:
            raise TypeError("Los temporales admiten int64, float64, str y None")


def read_record(fh: BinaryIO) -> dict:
    count = UINT32.unpack(_read_exact(fh, UINT32.size))[0]
    row = {}
    for _ in range(count):
        name = _read_text(fh)
        if name in row:
            raise ValueError("Campo duplicado en registro temporal")
        tag = TAG.unpack(_read_exact(fh, TAG.size))[0]
        if tag == NULL:
            value = None
        elif tag == INTEGER:
            value = INT64.unpack(_read_exact(fh, INT64.size))[0]
        elif tag == FLOAT:
            value = FLOAT64.unpack(_read_exact(fh, FLOAT64.size))[0]
        elif tag == TEXT:
            value = _read_text(fh)
        else:
            raise ValueError("Tipo de campo temporal desconocido")
        row[name] = value
    return row
