# PostgreSQL + PostGIS (GiST)

El contenedor expone PostgreSQL en `localhost:5433` para no interferir con una
instalación local. Usa `bd2` / `bd2` y la base `espacial`.

```bash
docker compose -f postgis/docker-compose.yml up -d
python -m pip install -r requirements-postgis.txt
docker compose -f postgis/docker-compose.yml exec postgis psql -U bd2 -d espacial -c '\\d puntos'
```

`init.sql` habilita PostGIS, crea `puntos.ubicacion` como
`GEOGRAPHY(POINT, 4326)` y el índice `puntos_ubicacion_gist`; también crea
`distritos.geom` como `GEOMETRY(MULTIPOLYGON, 4326)` con GiST. Las distancias
de `geography` se expresan en metros y usan `(lon, lat)`, al contrario del
motor propio (`POINT(lat, lon)`).

La carga reproducible se realiza desde Python:

```python
from benchmarks.generate_spatial_datasets import generate_points
from postgis.client import connect, load_points

connection = connect("postgresql://bd2:bd2@localhost:5433/espacial")
load_points(connection, generate_points(1000))
connection.close()
```

`postgis.client.range_query` usa `ST_DWithin`; `nearest_query` usa el operador
GiST `<->`. Ambos sirven para contrastar sus IDs con las consultas del R-tree.
