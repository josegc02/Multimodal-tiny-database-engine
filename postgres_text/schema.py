"""DDL de tablas por tamaño; el único campo indexado es contenido."""


def table_name(size):
    if type(size) is not int or size < 1:
        raise ValueError("size debe ser un entero positivo")
    return f"noticias_{size}"


def create_table(connection, size):
    from psycopg import sql

    name = table_name(size)
    connection.execute(sql.SQL("""
        CREATE TABLE texto.{} (
            id integer PRIMARY KEY,
            url text NOT NULL,
            contenido text NOT NULL,
            categoria text NOT NULL,
            tema text NOT NULL,
            full_text tsvector GENERATED ALWAYS AS
                (to_tsvector('pg_catalog.spanish'::regconfig, contenido)) STORED
        )
    """).format(sql.Identifier(name)))
