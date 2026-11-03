"""python -m postgres_text.search 'inflación precios alimentos' --size 1000"""

import argparse
import json
import os

from postgres_text.client import DEFAULT_DSN, connect
from postgres_text.queries import explain, search, search_tsquery


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query")
    parser.add_argument("--size", type=int, default=1000)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--dsn", default=os.environ.get("TEXT_POSTGRES_DSN", DEFAULT_DSN))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--explain", action="store_true")
    mode.add_argument("--tsquery", action="store_true", help="Aceptar operadores PostgreSQL explícitos")
    args = parser.parse_args(argv)
    with connect(args.dsn) as connection:
        action = explain if args.explain else search_tsquery if args.tsquery else search
        print(json.dumps(action(connection, args.size, args.query, args.top_k), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
