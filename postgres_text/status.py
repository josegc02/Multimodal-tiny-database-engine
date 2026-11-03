"""Inspección del servidor, del idioma y de los índices instalados."""

import argparse
import json
import os

from postgres_text.client import DEFAULT_DSN, connect
from postgres_text.schema import table_name


def status(connection, size):
    name = table_name(size)
    metadata = connection.execute("SELECT sha256,language FROM texto.dataset_loads WHERE size=%s", (size,)).fetchone()
    index = connection.execute("""
        SELECT i.indisvalid, am.amname, pg_get_indexdef(i.indexrelid)
        FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid
        JOIN pg_am am ON am.oid=c.relam
        WHERE i.indexrelid=to_regclass(%s) AND i.indrelid=to_regclass(%s)
    """, (f"texto.{name}_gin", f"texto.{name}")).fetchone()
    vector = connection.execute("""
        SELECT a.attgenerated, pg_get_expr(d.adbin,d.adrelid)
        FROM pg_attribute a JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
        WHERE a.attrelid=to_regclass(%s) AND a.attname='full_text'
    """, (f"texto.{name}",)).fetchone()
    return {"table": f"texto.{name}", "server_version": connection.info.server_version,
            "sha256": metadata[0] if metadata else None,
            "language": metadata[1] if metadata else None,
            "gin_valid": bool(index and index[0] and index[1] == "gin"),
            "index_definition": index[2] if index else None,
            "generated_expression": vector[1] if vector and vector[0] == "s" else None}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=int, default=1000)
    parser.add_argument("--dsn", default=os.environ.get("TEXT_POSTGRES_DSN", DEFAULT_DSN))
    args = parser.parse_args(argv)
    with connect(args.dsn) as connection:
        print(json.dumps(status(connection, args.size), indent=2))


if __name__ == "__main__":
    main()
