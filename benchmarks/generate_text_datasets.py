"""Genera noticias sintéticas reproducibles; ejecutar con python -m benchmarks.generate_text_datasets."""

import argparse
import csv
import hashlib
import json
import random
from pathlib import Path

from benchmarks.text_collection import CONTEXT, FIELDS, SIZES, TOPICS, VERSION
from benchmarks.text_queries import queries

OUTPUT = Path(__file__).resolve().parents[1] / "datasets/text/generated"


def documents(count, seed=42):
    """Flujo reproducible y estratificado; memoria independiente de count."""
    if type(count) is not int or count < 1:
        raise ValueError("count debe ser un entero positivo")
    rng = random.Random(seed)
    for number in range(count):
        category, topic, _, lead = TOPICS[number % len(TOPICS)]
        paragraphs = [f"Boletín {number + 1}. Actualidad de {category}. {lead}"]
        # Diferentes longitudes y tf; algunos documentos superan una página.
        for _ in range(rng.choice((1, 2, 3, 5, 8, 30))):
            paragraphs.append(rng.choice(CONTEXT))
            if rng.random() < 0.35:
                paragraphs.append(lead)
        # Menciones secundarias: compartir palabras no determina relevancia.
        if number % 5 == 0:
            other = TOPICS[(number + 3) % len(TOPICS)]
            paragraphs.append("En otras noticias: " + other[3])
        yield dict(zip(FIELDS, (number + 1, f"https://example.invalid/noticias/{number + 1}",
                               "\n".join(paragraphs), category, topic)))


def write_csv(path, fields, rows):
    with Path(path).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def generate(output=OUTPUT, sizes=SIZES, seed=42):
    sizes = tuple(sorted(sizes))
    if not sizes or any(type(n) is not int or n < 1 for n in sizes) or len(set(sizes)) != len(sizes):
        raise ValueError("sizes debe contener enteros positivos distintos")
    output = Path(output)
    # Reservar un directorio nuevo evita sobreescribir datasets anteriores.
    output.mkdir(parents=True, exist_ok=False)
    files = {}
    for size in sizes:
        path = output / f"noticias_{size}.csv"
        write_csv(path, FIELDS, documents(size, seed))
        files[path.name] = {"rows": size, "sha256": digest(path)}
    query_rows = queries()
    query_path = output / "queries.csv"
    write_csv(query_path, tuple(query_rows[0]), query_rows)
    files[query_path.name] = {"rows": len(query_rows), "sha256": digest(query_path)}
    manifest = {"version": VERSION, "seed": seed, "sizes": sizes, "language": "es",
                "source": "synthetic-editorial-topics", "fields": FIELDS, "files": files}
    (output / "metadata.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--sizes", type=int, nargs="+", default=SIZES)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)
    try:
        generate(args.output, args.sizes, args.seed)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
