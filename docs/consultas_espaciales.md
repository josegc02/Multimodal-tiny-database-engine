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
