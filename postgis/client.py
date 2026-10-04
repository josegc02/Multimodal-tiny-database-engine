"""Adaptador opcional de PostGIS para la comparación espacial (requirements-postgis.txt).

Las distancias se calculan sobre la **esfera**, igual que nuestro Haversine:
`geography` usa por defecto el elipsoide WGS84, que a 6 km difiere ~0,3% y
cambiaría qué puntos quedan dentro del radio. `ST_DWithin(..., false)` y el
operador `<->` usan la esfera.
"""

from __future__ import annotations

from engine.spatial.geometry import Point

INDEX = "puntos_ubicacion_gist"


def connect(dsn):
    """Conexión psycopg; se importa tarde para no exigir PostGIS en la CI."""
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("Instala requirements-postgis.txt para usar PostGIS") from exc
    return psycopg.connect(dsn)


def point_params(point):
    """(lon, lat): el orden de PostGIS y GeoJSON."""
    if not isinstance(point, Point):
        raise TypeError("Se esperaba Point")
    return point.lon, point.lat


def load_points(connection, rows):
    """Reemplaza el contenido de `puntos` (sin índice) con COPY."""
    with connection.cursor() as cursor:
        cursor.execute(f"DROP INDEX IF EXISTS {INDEX}")
        cursor.execute("TRUNCATE puntos")
        with cursor.copy("COPY puntos (id, nombre, categoria, ubicacion) FROM STDIN") as copy:
            for row in rows:
                lon, lat = point_params(row["ubicacion"])
                copy.write_row((row["id"], row["nombre"], row["categoria"], f"SRID=4326;POINT({lon!r} {lat!r})"))
        cursor.execute("ANALYZE puntos")
    connection.commit()


def build_index(connection):
    """Crea el índice GiST (lo que se cronometra como construcción)."""
    with connection.cursor() as cursor:
        cursor.execute(f"CREATE INDEX {INDEX} ON puntos USING GIST (ubicacion)")
        cursor.execute("ANALYZE puntos")
    connection.commit()


def index_size(connection):
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_relation_size(%s::regclass)", (INDEX,))
        return cursor.fetchone()[0]


def range_query(connection, center, radius_m):
    """ids a `radius_m` metros o menos (distancia esférica, con el índice GiST)."""
    lon, lat = point_params(center)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id FROM puntos WHERE ST_DWithin(ubicacion, "
            "ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, %s, false)",
            (lon, lat, radius_m),
        )
        return [row[0] for row in cursor]


def nearest_query(connection, center, k):
    """[(id, distancia)] de los k más cercanos.

    Solo se ordena por `<->`: agregar otra clave (p. ej. `, id`) impide que
    PostgreSQL use el índice y lo convierte en scan + sort de toda la tabla.
    """
    lon, lat = point_params(center)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id, ubicacion <-> ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography AS d "
            "FROM puntos ORDER BY d LIMIT %s",
            (lon, lat, k),
        )
        return [(row[0], row[1]) for row in cursor]
