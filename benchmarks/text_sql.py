"""SQL de carga para la interfaz existente; el CSV es común a las técnicas."""

from pathlib import Path


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def load_sql(csv_path, size):
    if type(size) is not int or size < 1:
        raise ValueError("size debe ser un entero positivo")
    table = f"noticias_{size}"
    return (
        f"CREATE TABLE {table} (id INT, url TEXT, contenido TEXT, categoria TEXT, tema TEXT);\n"
        f"COPY {table} FROM {literal(Path(csv_path).resolve())} WITH (FORMAT CSV, HEADER TRUE);\n"
        f"CREATE INDEX noticias_texto_{size} ON {table} (contenido) USING SPIMI WITH (LANGUAGE = 'es');\n"
    )
