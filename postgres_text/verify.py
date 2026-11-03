"""Comparación exacta CSV/PostgreSQL; no mide rendimiento."""

import argparse
import json
import os
from itertools import zip_longest
from pathlib import Path

from benchmarks.generate_text_datasets import digest
from benchmarks.text_collection import FIELDS, SIZES
from benchmarks.text_validation import read_documents
from postgres_text.client import DEFAULT_DSN, connect
from postgres_text.schema import table_name


def verify(connection, csv_path, size):
    from psycopg import sql

    name = table_name(size)
    fingerprint = digest(csv_path)
    metadata = connection.execute("SELECT sha256,language FROM texto.dataset_loads WHERE size=%s", (size,)).fetchone()
    if metadata != (fingerprint, "spanish"):
        raise ValueError("La procedencia registrada no coincide con el CSV")
    count = 0
    with connection.transaction(), connection.cursor(name="verify_text_rows") as cursor:
        cursor.execute(sql.SQL("SELECT id,url,contenido,categoria,tema FROM texto.{} ORDER BY id").format(sql.Identifier(name)))
        source = read_documents(csv_path)
        try:
            for expected, actual in zip_longest(source, cursor):
                if expected is None or actual != tuple(expected[field] for field in FIELDS):
                    raise ValueError(f"Contenido diferente en documento {count + 1}")
                count += 1
        finally:
            source.close()
    if count != size:
        raise ValueError("Cardinalidad incorrecta")
    return {"size": size, "sha256": fingerprint, "exact_match": True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", default=os.environ.get("TEXT_POSTGRES_DSN", DEFAULT_DSN))
    parser.add_argument("--dataset-dir", type=Path, default=Path("datasets/text/generated"))
    parser.add_argument("--sizes", type=int, nargs="+", default=SIZES)
    args = parser.parse_args(argv)
    with connect(args.dsn) as connection:
        for size in args.sizes:
            print(json.dumps(verify(connection, args.dataset_dir / f"noticias_{size}.csv", size)), flush=True)


if __name__ == "__main__":
    main()
