# Consultas espaciales: criterios verificados

## #20 — Rango por radio

- [x] Búsqueda rectangular con poda por intersección de MBR.
- [x] Radio inclusivo: MBR conservador y distancia exacta `<= radio`.
- [x] Métricas `Metric.HAVERSINE` y `Metric.EUCLIDEAN`, en metros.
- [x] Contadores por consulta: nodos, hojas, candidatos, refinados y resultados.
- [x] Comparación con scan, reapertura, duplicados, borde, polos y antimeridiano.

API: `tree.range_query(Point(lat, lon), radio_m, metric)` devuelve
`[(Point, RID, distancia_m)]`, ordenados por distancia y luego RID.
`last_stats.refined` cuenta evaluaciones exactas después del filtro MBR;
`candidates` cuenta entradas inspeccionadas en hojas.

Validación: `python -m unittest tests.spatial.test_range tests.indexes.test_rtree -q`.

## #21 — k vecinos más cercanos

- [x] Best-first con cola de prioridad de nodos por MINDIST y heap de k respuestas.
- [x] Ambas métricas en metros.
- [x] Empates por RID (página, slot, archivo); `k=0` vacío y `k>N` todos los puntos.
- [x] Comparación con fuerza bruta, reapertura, borrados, duplicados y poda.

API: `tree.knn(Point(lat, lon), k, metric)` devuelve `[(Point, RID, distancia_m)]`.
Los nodos empatados con el peor vecino se visitan para respetar el desempate.
Validación: `python -m unittest tests.spatial.test_knn -q`.

## #22 — Polígonos y distritos GeoJSON

- [x] Anillos de vértices y MBR.
- [x] Filtro MBR del R-Tree y ray casting exacto.
- [x] Bordes incluidos, polígonos convexos/cóncavos y agujeros.
- [x] Lectura de Polygon, MultiPolygon, Feature y FeatureCollection GeoJSON.
- [x] Carga de distritos por propiedad configurable y tests con fixture sintético.

`tree.within_polygon(polygon)` devuelve pares `(Point, RID)` ordenados por RID.
`load_districts(path, name_field="nombre")` en `engine.spatial.geometry` devuelve
un diccionario distrito → tupla de polígonos. Para un distrito multipartes se
unen los resultados por RID. GeoJSON usa `[lon, lat]`; el cargador invierte ese
orden. La fixture `tests/spatial/fixtures/districts.geojson` es ficticia y solo
prueba el cargador; los datasets geográficos de la entrega corresponden a #25.

El contorno y bordes de agujeros se incluyen (semántica de cobertura), pero el
interior de agujeros se excluye. Los anillos deben ser simples, sin cruces del
antimeridiano; se rechazan anillos degenerados. No se reparan geometrías inválidas.
Validación: `python -m unittest tests.spatial.test_polygon -q`.

## #23 — Integración SQL espacial

- [x] Columna POINT de 16 bytes en Heap, Sequential y B+ agrupado.
- [x] Literales POINT(lat, lon) y POLYGON((lat, lon), ...), con validación.
- [x] Distancia en WHERE y ORDER BY/LIMIT para rango y k-NN.
- [x] WITHIN para polígonos, con bordes incluidos.
- [x] HAVERSINE/EUCLIDEAN seleccionable, por defecto Haversine.
- [x] CREATE INDEX USING RTREE y mantenimiento desde el catálogo.
- [x] R-Tree vigente para predicados compatibles; scan equivalente sin índice.
- [x] EXPLAIN indica índice, métrica, filtro y refinamiento. ANALYZE añade
  nodos/hojas visitados, candidatos y evaluaciones exactas reales.
- [x] Tests del enunciado, oráculos scan/distancia, rollback, COPY, índices
  inválidos, cambios de RID, temporales externos y tablas vacías.

Ejemplo ejecutable desde el editor del frontend (cada SELECT puede ejecutarse solo):

```sql
CREATE TABLE tiendas (id INT PRIMARY KEY, nombre VARCHAR(40), ubicacion POINT);
INSERT INTO tiendas VALUES
  (1, 'Centro', POINT(-12.0464, -77.0428)),
  (2, 'Sur', POINT(-12.12, -77.03)),
  (3, 'Norte', POINT(-12.02, -77.04));
CREATE INDEX tiendas_geo ON tiendas (ubicacion) USING RTREE;

SELECT * FROM tiendas
WHERE distancia(ubicacion, POINT(-12.0464, -77.0428)) < 5000;

SELECT id, nombre, distancia(ubicacion, POINT(-12.0464, -77.0428)) AS metros
FROM tiendas ORDER BY metros LIMIT 10 USING HAVERSINE;

SELECT * FROM tiendas WHERE WITHIN(ubicacion,
  POLYGON((-12.1, -77.1), (-12.1, -77), (-12, -77), (-12, -77.1)));

EXPLAIN ANALYZE SELECT * FROM tiendas
WHERE distancia(ubicacion, POINT(-12.0464, -77.0428)) <= 5000 USING EUCLIDEAN;
```

También se admite `distancia(ubicacion, POINT(...), 'euclidean')`; ese argumento
prevalece sobre `USING`. En DELETE se elige la métrica con el tercer argumento.
El `mi_ubicacion` del enunciado puede reemplazarse por el literal de consulta o
ser una columna POINT; no existen variables SQL de sesión. Si el centro cambia
por fila, se calcula por scan. El tipo POINT no admite NULL, claves primarias,
foráneas ni índices HASH/BTREE; una columna INT identifica/ordena la tabla.

El optimizador utiliza k-NN para una tabla, un ORDER BY de distancia ASC y LIMIT,
con OFFSET opcional. Con WHERE amplía progresivamente el prefijo de vecinos
hasta reunir `LIMIT + OFFSET` filas elegibles; los contadores acumulan todas
esas búsquedas. Con múltiples claves de orden, DESC, JOIN, DISTINCT o agregación
se conserva el sort completo, para no alterar los resultados. Los costos del
R-Tree son estimaciones conservadoras (altura del árbol + páginas de tabla),
no tiempos medidos. Los planes muestran el sort final cuando aún se ejecuta.

COPY recibe cada punto en una celda CSV `"POINT(-12.0464, -77.0428)"`.
El botón de inferencia CSV todavía propone tipos escalares: crear primero la
tabla POINT o ajustar manualmente el CREATE TABLE sugerido antes de cargar.
Los encabezados de resultados vacíos con LIMIT/OFFSET se conservan también en
el frontend, buscando Project por debajo del nodo Limit.

Validación: `python -m unittest tests.spatial.test_sql_spatial -v` y suite completa
`python -m unittest discover tests -q`. El mapa y benchmarks son #24–#27.
