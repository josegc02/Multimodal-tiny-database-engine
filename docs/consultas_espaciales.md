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
