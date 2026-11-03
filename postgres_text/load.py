"""python -m postgres_text.load --dataset-dir datasets/text/generated"""

import argparse
import json
import os
from pathlib import Path

from benchmarks.text_collection import SIZES
from benchmarks.text_validation import validate_bundle
from postgres_text.client import DEFAULT_DSN, analyze, build_index, connect, initialize, load_csv


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", default=os.environ.get("TEXT_POSTGRES_DSN", DEFAULT_DSN))
    parser.add_argument("--dataset-dir", type=Path, default=Path("datasets/text/generated"))
    parser.add_argument("--sizes", type=int, nargs="+", default=SIZES)
    args = parser.parse_args(argv)
    bundle = validate_bundle(args.dataset_dir)
    if len(set(args.sizes)) != len(args.sizes) or any(size not in bundle for size in args.sizes):
        parser.error("Los tamaños deben ser distintos y existir en el bundle validado")
    with connect(args.dsn) as connection:
        initialize(connection)
        for size in args.sizes:
            # Tabla, datos, metadatos e índice se publican juntos; rollback en fallo.
            with connection.transaction():
                result = load_csv(connection, args.dataset_dir / f"noticias_{size}.csv", size)
                build_index(connection, size)
                analyze(connection, size)
            print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
