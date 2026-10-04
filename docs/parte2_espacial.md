# Parte 2: Base de Datos Espacial

Plan de trabajo y estructura de la Parte 2 (entrega parcial, semana 8). Cada archivo base tiene la interfaz definida y sus métodos lanzan `NotImplementedError` con el issue donde se implementan.

## Qué pide el enunciado

- **Índice R-Tree** para puntos 2D (latitud, longitud) con:
  - consultas por rango ("tiendas en un radio de 5 km");
  - k-NN ("las 10 gasolineras más cercanas");
  - intersección con polígonos ("sucursales dentro de un distrito").
- **Métricas Euclidiana y geodésica (Haversine).**
- **Panel de mapa** interactivo con los resultados resaltados.
- **Extensión SQL**, por ejemplo:
  ```sql
  SELECT * FROM tiendas WHERE distancia(ubicacion, POINT(-12.0464, -77.0428)) < 5000;
  SELECT * FROM restaurantes ORDER BY distancia(ubicacion, mi_ubicacion) LIMIT 10;
  ```
- **Comparación experimental** de Secuencial vs R-Tree vs GiST (PostgreSQL):
  - consultas: radio de 1, 5 y 10 km, y k-NN con k = 10, 50 y 100;
  - datasets: 1.000, 10.000 y 100.000 puntos;
  - mediciones: construcción, consulta (promedio de 100) y memoria/disco.

## Estructura y issues

| Archivo | Contenido | Issue |
| :--- | :--- | :---: |
| `engine/spatial/geometry.py` | `Point`, `MBR` (área, unión, enlargement, intersección) y `Polygon` (MBR, ray casting, GeoJSON) | #18, #22 |
| `engine/spatial/distance.py` | Euclidiana, Haversine, MINDIST punto-MBR y radio → MBR | #19 |
| `engine/indexes/rtree.py` | R-Tree en disco: inserción, split, eliminación, rango, k-NN y polígono | #18, #20, #21, #22 |
| `engine/query/` (lexer, parser, ast, catalog, optimizer, explain) | Tipo `POINT`, `distancia(...)`, `ORDER BY distancia LIMIT k`, polígonos, `CREATE INDEX ... USING RTREE`, plan de ejecución | #23 |
| `frontend/panel_mapa.py` | Panel de mapa (puntos, resultados, radio y polígono) | #24 |
| `benchmarks/generate_spatial_datasets.py`, `datasets/spatial/` | Puntos de 1K/10K/100K y polígonos de distritos | #25 |
| `postgis/` | PostgreSQL + PostGIS con Docker, esquema y consultas GiST equivalentes | #26 |
| `benchmarks/bench_spatial.py` | Benchmark Secuencial vs R-Tree vs GiST | #27 |
| `tests/spatial/` | Pruebas de geometría, métricas, R-Tree y SQL espacial | todos |

## Orden sugerido

1. **#19 Métricas** y la parte de geometría de **#18**: son la base de todo lo demás y se prueban solas.
2. **#18 R-Tree** (inserción, split, persistencia) y **#25 datasets**, en paralelo.
3. **#20 rango**, **#21 k-NN** y **#22 polígonos**, comparando siempre contra la búsqueda secuencial (fuerza bruta).
4. **#23 SQL espacial**, que integra el R-Tree al catálogo y al optimizador.
5. **#24 mapa** y **#26 PostGIS**, en paralelo.
6. **#27 benchmark** e informe.

## Decisiones a tomar

- **Orden de coordenadas.** Proponemos `POINT(lat, lon)`, como el ejemplo del enunciado. PostGIS y GeoJSON usan `(lon, lat)`, así que hay que invertir el orden al cargar datos y al comparar con GiST.
- **Métrica Euclidiana (#19).**
  - Opción 1: grados escalados a metros con una proyección equirectangular, para que `< 5000` signifique 5 km con ambas métricas.
  - Opción 2: grados sin escalar.
  - Se recomienda la opción 1; hay que medir su error frente a Haversine.
- **Elección de la métrica en SQL (#23):** `USING HAVERSINE | EUCLIDEAN` al final de la consulta, o un tercer argumento `distancia(col, punto, 'haversine')`.
- **Polígonos en SQL (#23):**
  - Opción 1: `WITHIN(col, POLYGON((lat lon, ...)))`.
  - Opción 2: por nombre de distrito cargado desde GeoJSON.
- **Almacenamiento del tipo `POINT`:** dos `float` de 8 bytes en `engine/storage/record.py` (16 bytes por punto).
- **Split del R-Tree (#18):** cuadrático (mejor calidad) o lineal (más rápido). Opcional: *bulk loading* STR para la construcción.
- **Mapa (#24):**
  - Opción 1: `tkintermapview`, un widget Tk con OpenStreetMap integrado en la ventana actual.
  - Opción 2: Leaflet en el navegador, con un HTML generado o un endpoint local.
- **Dependencias nuevas:**
  - `psycopg[binary]`, para el benchmark contra PostGIS;
  - posiblemente `tkintermapview`.
  - Se agregan a `requirements.txt` cuando se usen. La CI no levanta PostGIS, así que el benchmark debe poder correr sin él (`--sin-postgis`).

## PostgreSQL + PostGIS

```bash
docker compose -f postgis/docker-compose.yml up -d     # puerto 5433, usuario/clave bd2/bd2, base "espacial"
docker compose -f postgis/docker-compose.yml down -v    # detener y borrar los datos
```

`postgis/init.sql` crea la extensión, las tablas `puntos` (`geography`, distancias en metros) y `distritos`, y deja comentadas las consultas equivalentes:
- `ST_DWithin`, para el rango;
- `ORDER BY <-> LIMIT k`, para k-NN;
- `ST_Within`, para la intersección con polígonos.
