"""Carga persistente y aislada: python -m benchmarks.load_text_dataset CSV --output DIR."""

import argparse
import json
from contextlib import ExitStack
from pathlib import Path

from benchmarks.generate_text_datasets import digest
from benchmarks.text_validation import read_documents, validate_documents
from engine.indexes.spimi import SpimiIndex
from engine.storage.heap_file import HeapFile
from engine.storage.text_store import TextStore


def schema(texts):
    return [("id", "int"), ("url", "text", texts), ("contenido", "text", texts),
            ("categoria", "text", texts), ("tema", "text", texts)]


def load_dataset(csv_path, output):
    """Valida primero, inserta en flujo y construye SPIMI al terminar la carga."""
    csv_path, output = Path(csv_path).resolve(), Path(output)
    count = validate_documents(csv_path)
    source_sha256 = digest(csv_path)
    output.mkdir(parents=True, exist_ok=False)
    with ExitStack() as resources:
        texts = TextStore(str(output / "noticias.text"))
        resources.callback(texts.close)
        storage = HeapFile(str(output / "noticias.db"), schema(texts))
        resources.callback(storage.close)
        for row in read_documents(csv_path):
            storage.insert(row)
        index = SpimiIndex(str(output / "noticias.spimi"), "es")
        resources.callback(index.close)
        index.build((row["contenido"], rid) for rid, row in storage.scan())
        if index.doc_count != count:
            raise ValueError("El número de documentos indexados no coincide con el CSV")
    metadata = {"source": str(csv_path), "source_sha256": source_sha256,
                "documents": count, "language": "es",
                "table": "noticias", "indexed_column": "contenido", "complete": True}
    (output / "load.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return metadata


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(load_dataset(args.csv, args.output), indent=2))
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
