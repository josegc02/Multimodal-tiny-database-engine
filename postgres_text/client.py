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


def load_csv(connection, csv_path, size):
    """COPY binario del CSV original, transacción completa y rechazo de recarga."""
    from psycopg import sql
    from benchmarks.generate_text_datasets import digest
    from benchmarks.text_validation import validate_documents

    name = table_name(size)
    csv_path = Path(csv_path)
    if validate_documents(csv_path) != size:
        raise ValueError("El CSV no contiene el tamaño solicitado")
    fingerprint = digest(csv_path)
    with connection.transaction():
        create_table(connection, size)
        with connection.cursor() as cursor:
            command = sql.SQL("COPY texto.{} (id,url,contenido,categoria,tema) "
                              "FROM STDIN WITH (FORMAT CSV, HEADER TRUE, ENCODING 'UTF8')").format(sql.Identifier(name))
            with cursor.copy(command) as copy, csv_path.open("rb") as stream:
                while block := stream.read(1024 * 1024):
                    copy.write(block)
        loaded = connection.execute(sql.SQL("SELECT count(*) FROM texto.{}").format(sql.Identifier(name))).fetchone()[0]
        if loaded != size or digest(csv_path) != fingerprint:
            raise ValueError("El CSV cambió durante la carga")
        connection.execute("INSERT INTO texto.dataset_loads (size,sha256,source_name,language) "
                           "VALUES (%s,%s,%s,'spanish')", (size, fingerprint, csv_path.name))
    return {"size": size, "sha256": fingerprint, "table": f"texto.{name}"}
