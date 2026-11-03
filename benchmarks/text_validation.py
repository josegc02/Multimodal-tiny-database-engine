"""Lectura estricta de documentos antes de cargar el motor."""

import csv
from pathlib import Path

from benchmarks.text_collection import FIELDS


def read_documents(path):
    """IDs consecutivos evitan duplicados sin guardar todos los textos en RAM."""
    with Path(path).open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != FIELDS:
            raise ValueError(f"Cabecera incorrecta; se esperaba {FIELDS}")
        count = 0
        for count, row in enumerate(reader, 1):
            if None in row or any(not row[field] for field in FIELDS):
                raise ValueError(f"Documento {count}: campos vacíos o columnas incorrectas")
            if row["id"] != str(count):
                raise ValueError(f"Documento {count}: ID no consecutivo")
            row["id"] = count
            yield row
        if not count:
            raise ValueError("El corpus está vacío")


def validate_documents(path):
    return sum(1 for _ in read_documents(path))
