"""Cliente opcional para cargar y consultar los mismos CSV del motor."""

from pathlib import Path

from postgres_text.schema import create_table, table_name

DEFAULT_DSN = "postgresql://bd2:bd2@localhost:5434/texto"


def connect(dsn=DEFAULT_DSN):
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("Instala requirements-text-postgres.txt") from exc
    return psycopg.connect(dsn, autocommit=True, connect_timeout=10)


def initialize(connection):
    with connection.transaction():
        connection.execute(Path(__file__).with_name("init.sql").read_text(encoding="utf-8"))
