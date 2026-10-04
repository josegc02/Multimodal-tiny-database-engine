"""Comparación experimental de la Parte 2: Secuencial vs R-Tree vs GiST (issue #27).

Uso previsto:
    python benchmarks/bench_spatial.py                   # 1K, 10K y 100K, 3 repeticiones
    python benchmarks/bench_spatial.py --sin-postgis     # sin PostgreSQL disponible

Mide, para cada técnica y tamaño:
- tiempo de construcción del índice;
- consultas por rango con radio de 1, 5 y 10 km (promedio de 100 consultas);
- consultas k-NN con k = 10, 50 y 100 (promedio de 100 consultas);
- espacio en disco y memoria.

Sigue la metodología de la Parte 1 (benchmarks/_common.py): CSV con media y
desviación estándar, gráficas log-log por operación y metadatos del entorno.
GiST se consulta en PostgreSQL + PostGIS (postgis/docker-compose.yml) con
psycopg; los tres deben devolver los mismos resultados.
Estado: estructura base.
"""

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TECHNIQUES = ("Secuencial", "R-Tree", "GiST (PostGIS)")
RADII_M = (1_000, 5_000, 10_000)
KS = (10, 50, 100)
QUERIES = 100
METRICS = (
    ["tiempo_construccion_seg"]
    + [f"tiempo_rango_{r // 1000}km_seg" for r in RADII_M]
    + [f"tiempo_knn_{k}_seg" for k in KS]
    + ["espacio_disco_bytes", "memoria_bytes", "nodos_visitados_promedio"]
)

# Conexión por defecto al contenedor de postgis/docker-compose.yml.
POSTGIS_DSN = "postgresql://bd2:bd2@localhost:5433/espacial"


def bench_sequential(points, queries):
    """Scan completo calculando la distancia exacta. Pendiente: issue #27."""
    raise NotImplementedError("Pendiente: issue #27")


def bench_rtree(points, queries, directory):
    """R-Tree propio (engine/indexes/rtree.py). Pendiente: issue #27."""
    raise NotImplementedError("Pendiente: issue #27")


def bench_gist(points, queries, dsn=POSTGIS_DSN):
    """PostGIS con índice GiST: ST_DWithin y ORDER BY <-> LIMIT k. Pendiente: issue #27."""
    raise NotImplementedError("Pendiente: issue #27")


def main() -> None:
    raise NotImplementedError("Pendiente: issue #27")


if __name__ == "__main__":
    main()
