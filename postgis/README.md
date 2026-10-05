# PostgreSQL + PostGIS (GiST)

Contenedor para comparar nuestro R-Tree con el índice GiST de PostGIS (Parte 2).

- **Imagen:** PostgreSQL 16 + PostGIS 3.4.
- **Acceso:** usuario/clave `bd2`/`bd2` y base `espacial`.
- **Puerto:** 5433 por defecto, para no chocar con un PostgreSQL local.

```bash
python -m pip install -r requirements-postgis.txt                 # psycopg
docker compose -f postgis/docker-compose.yml up -d
POSTGIS_PORT=5434 docker compose -f postgis/docker-compose.yml up -d   # si el 5433 está ocupado
docker compose -f postgis/docker-compose.yml exec postgis psql -U bd2 -d espacial -c '\d puntos'
docker compose -f postgis/docker-compose.yml down                 # detener (con -v también borra los datos)
```

`init.sql` habilita PostGIS y crea dos tablas:
- `puntos`, con `ubicacion GEOGRAPHY(POINT, 4326)`;
- `distritos`, con `geom GEOMETRY(MULTIPOLYGON, 4326)` y su índice GiST.

PostGIS usa el orden `(lon, lat)`, al revés que nuestro motor (`POINT(lat, lon)`). `client.py` hace la conversión.

## Uso desde Python (`postgis/client.py`)

```python
from benchmarks.generate_spatial_datasets import generate_points
from postgis.client import build_index, connect, load_points, nearest_query, range_query
from engine.spatial.geometry import Point

connection = connect("postgresql://bd2:bd2@localhost:5433/espacial")
load_points(connection, generate_points(1000))   # COPY de los puntos, sin índice
build_index(connection)                          # CREATE INDEX ... USING GIST
centro = Point(-12.0464, -77.0428)
range_query(connection, centro, 5000)            # ids a 5 km o menos
nearest_query(connection, centro, 10)            # [(id, distancia)] de los 10 más cercanos
connection.close()
```

Dos detalles para que los resultados coincidan con nuestro motor:
- **Distancia sobre la esfera.** `geography` mide por defecto sobre el elipsoide WGS84, que a 6 km difiere ~0,3% de nuestro Haversine. Por eso `range_query` usa `ST_DWithin(..., false)`, que mide sobre la esfera. El operador `<->` ya usa la esfera.
- **k-NN con el índice.** `nearest_query` ordena solo por `ubicacion <-> punto`. Si se agrega otra clave de orden (`ORDER BY ubicacion <-> punto, id`), PostgreSQL ya no usa el índice y recorre y ordena toda la tabla.

El benchmark (`python -m benchmarks.bench_spatial`) usa estas funciones. Si el contenedor usa otro puerto, se indica con `--postgis-dsn`.
