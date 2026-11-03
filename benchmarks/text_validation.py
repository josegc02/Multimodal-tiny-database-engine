"""Lectura estricta de documentos antes de cargar el motor."""

import csv
import hashlib
import json
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


def validate_bundle(directory):
    """Verifica integridad, cardinalidades y qrels contra etiquetas editoriales."""
    from benchmarks.text_queries import queries
    from benchmarks.text_relevance import judgments

    directory = Path(directory)
    metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
    for name, expected in metadata["files"].items():
        if Path(name).name != name:
            raise ValueError("Ruta de archivo inválida en metadata")
        with (directory / name).open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != expected["sha256"]:
                raise ValueError(f"Checksum incorrecto: {name}")
        with (directory / name).open(encoding="utf-8", newline="") as stream:
            if sum(1 for _ in csv.DictReader(stream)) != expected["rows"]:
                raise ValueError(f"Cardinalidad incorrecta: {name}")
    with (directory / "queries.csv").open(encoding="utf-8", newline="") as stream:
        expected = [{key: str(value) for key, value in q.items()} for q in queries()]
        if list(csv.DictReader(stream)) != expected:
            raise ValueError("Consultas no corresponden a la versión del generador")
    summary = {}
    for size in metadata["sizes"]:
        path = directory / f"noticias_{size}.csv"
        if validate_documents(path) != size:
            raise ValueError(f"Tamaño incorrecto: {path.name}")
        relevant = {q["query_id"]: 0 for q in queries()}
        with (directory / f"qrels_{size}.csv").open(encoding="utf-8", newline="") as stream:
            actual = iter(csv.DictReader(stream))
            for expected in judgments(read_documents(path), queries()):
                if next(actual, None) != {key: str(value) for key, value in expected.items()}:
                    raise ValueError(f"Juicio incorrecto en tamaño {size}")
                relevant[expected["query_id"]] += 1
            if next(actual, None) is not None:
                raise ValueError("Sobran juicios de relevancia")
        summary[size] = {"documents": size, "relevant_per_query": relevant}
    return summary


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Verificar corpus y qrels del issue #49")
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(validate_bundle(args.directory), indent=2))
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(1, f"Error: {exc}\n")
