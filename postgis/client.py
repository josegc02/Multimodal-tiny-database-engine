"""Adaptador opcional para cargar y consultar PostGIS en la comparación espacial."""

from __future__ import annotations

from engine.spatial.geometry import Point


def connect(dsn):
    """Abre una conexión psycopg; se importa tarde para no exigir PostGIS en la CI."""
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("Instala requirements-postgis.txt para usar PostGIS") from exc
    return psycopg.connect(dsn)


def point_params(point):
    """Parámetros (lon, lat), que es el orden requerido por PostGIS/GeoJSON."""
    if not isinstance(point, Point):
        raise TypeError("Se esperaba Point")
    return point.lon, point.lat


def load_points(connection, rows):
    """Reemplaza ``puntos`` con filas id/nombre/categoria/ubicacion y crea su GiST."""
    values = [
        (row["id"], row["nombre"], row["categoria"], *point_params(row["ubicacion"]))
        for row in rows
    ]
    with connection.cursor() as cursor:
        cursor.execute("TRUNCATE puntos")
        cursor.executemany(
            "INSERT INTO puntos (id, nombre, categoria, ubicacion) "
            "VALUES (%s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography)",
            values,
        )
        cursor.execute("DROP INDEX IF EXISTS puntos_ubicacion_gist")
        cursor.execute("CREATE INDEX puntos_ubicacion_gist ON puntos USING GIST (ubicacion)")
    connection.commit()


def range_query(connection, center, radius_m):
    lon, lat = point_params(center)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id FROM puntos WHERE ST_DWithin(ubicacion, "
            "ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, %s) ORDER BY id",
            (lon, lat, radius_m),
        )
        return [row[0] for row in cursor]


def nearest_query(connection, center, k):
    lon, lat = point_params(center)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id FROM puntos ORDER BY ubicacion <-> "
            "ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, id LIMIT %s",
            (lon, lat, k),
        )
        return [row[0] for row in cursor]
