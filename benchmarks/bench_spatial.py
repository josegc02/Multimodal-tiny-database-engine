"""Comparación experimental: scan secuencial, R-Tree propio y GiST/PostGIS.

Ejemplo rápido (sin Docker):
    python -m benchmarks.bench_spatial --sizes 200 --queries 5 --repetitions 1 --sin-postgis
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import tempfile
import time
import tracemalloc

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmarks import _common
from benchmarks.generate_spatial_datasets import generate_points, generate_queries
from engine.indexes.rtree import RTree
from engine.spatial.distance import distance
from engine.spatial.geometry import Point
from engine.storage.record import RID

TECHNIQUES = ("Secuencial", "R-Tree", "GiST (PostGIS)")
RADII_M = (1_000, 5_000, 10_000)
KS = (10, 50, 100)
POSTGIS_DSN = "postgresql://bd2:bd2@localhost:5433/espacial"
METRICS = (["tiempo_construccion_seg"]
           + [f"tiempo_rango_{radius // 1000}km_seg" for radius in RADII_M]
           + [f"tiempo_knn_{k}_seg" for k in KS]
           + ["espacio_disco_bytes", "memoria_bytes", "nodos_visitados_promedio"])


def _centers(queries):
    return [Point(query["lat"], query["lon"]) for query in queries]


def _mean_time(action):
    started = time.perf_counter()
    action()
    return time.perf_counter() - started


def _expected_range(points, center, radius):
    return {row["id"] for row in points if distance(center, row["ubicacion"]) <= radius}


def _expected_knn(points, center, k):
    return [row["id"] for row in sorted(
        points, key=lambda row: (distance(center, row["ubicacion"]), row["id"])
    )[:k]]


def bench_sequential(points, queries):
    """Scan exacto Haversine; referencia de corrección y línea base."""
    centers = _centers(queries)
    result = {"tiempo_construccion_seg": 0.0, "espacio_disco_bytes": 0,
              "memoria_bytes": 0, "nodos_visitados_promedio": 0.0}
    for radius in RADII_M:
        result[f"tiempo_rango_{radius // 1000}km_seg"] = _mean_time(
            lambda: [[row["id"] for row in points if distance(center, row["ubicacion"]) <= radius]
                     for center in centers]) / len(centers)
    for k in KS:
        result[f"tiempo_knn_{k}_seg"] = _mean_time(
            lambda: [sorted(points, key=lambda row: (distance(center, row["ubicacion"]), row["id"]))[:k]
                     for center in centers]) / len(centers)
    return result


def bench_rtree(points, queries, directory):
    """Construye el índice persistente y mide el promedio de sus consultas exactas."""
    centers = _centers(queries)
    path = Path(directory) / "points.rtree"
    tracemalloc.start()
    started = time.perf_counter()
    tree = RTree(path)
    for row in points:
        tree.insert(row["ubicacion"], RID(row["id"] + 1, 0, "main"))
    tree.flush()
    build = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    result = {"tiempo_construccion_seg": build, "espacio_disco_bytes": os.path.getsize(path),
              "memoria_bytes": peak, "nodos_visitados_promedio": 0.0}
    try:
        node_counts = []
        for radius in RADII_M:
            elapsed = _mean_time(lambda: [tree.range_query(center, radius) for center in centers])
            result[f"tiempo_rango_{radius // 1000}km_seg"] = elapsed / len(centers)
            for center in centers:
                actual = {rid.page_id - 1 for _, rid, _ in tree.range_query(center, radius)}
                assert actual == _expected_range(points, center, radius), "R-Tree y scan difieren en rango"
            node_counts.append(tree.last_stats.nodes_visited)
        for k in KS:
            elapsed = _mean_time(lambda: [tree.knn(center, k) for center in centers])
            result[f"tiempo_knn_{k}_seg"] = elapsed / len(centers)
            for center in centers:
                actual = [rid.page_id - 1 for _, rid, _ in tree.knn(center, k)]
                assert actual == _expected_knn(points, center, k), "R-Tree y scan difieren en k-NN"
            node_counts.append(tree.last_stats.nodes_visited)
        result["nodos_visitados_promedio"] = sum(node_counts) / len(node_counts)
        return result
    finally:
        tree.close()


def bench_gist(points, queries, dsn=POSTGIS_DSN):
    """Mide ST_DWithin y el k-NN GiST real. Requiere el contenedor y psycopg."""
    from postgis.client import connect, load_points, nearest_query, range_query

    centers = _centers(queries)
    connection = connect(dsn)
    try:
        build = _mean_time(lambda: load_points(connection, points))
        result = {"tiempo_construccion_seg": build, "espacio_disco_bytes": _common.NA,
                  "memoria_bytes": _common.NA, "nodos_visitados_promedio": _common.NA}
        for radius in RADII_M:
            result[f"tiempo_rango_{radius // 1000}km_seg"] = _mean_time(
                lambda: [range_query(connection, center, radius) for center in centers]) / len(centers)
            for center in centers:
                assert set(range_query(connection, center, radius)) == _expected_range(points, center, radius)
        for k in KS:
            result[f"tiempo_knn_{k}_seg"] = _mean_time(
                lambda: [nearest_query(connection, center, k) for center in centers]) / len(centers)
            for center in centers:
                assert nearest_query(connection, center, k) == _expected_knn(points, center, k)
        return result
    finally:
        connection.close()


def _arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", type=int, nargs="+", default=(1_000, 10_000, 100_000))
    parser.add_argument("--queries", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--output-dir", type=Path, default=_common.RESULTS)
    parser.add_argument("--sin-postgis", action="store_true")
    parser.add_argument("--postgis-dsn", default=POSTGIS_DSN)
    args = parser.parse_args(argv)
    if any(size < 1 for size in args.sizes) or len(set(args.sizes)) != len(args.sizes):
        parser.error("--sizes debe contener enteros positivos distintos")
    if args.queries < 1 or args.repetitions < 1:
        parser.error("--queries y --repetitions deben ser positivos")
    args.sizes = sorted(args.sizes)
    return args


def main(argv=None):
    args = _arguments(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    runs = []
    for size in args.sizes:
        points, queries = generate_points(size, args.seed), generate_queries(args.queries, args.seed + 1)
        for repetition in range(args.repetitions):
            _common.progress(f"N={size}, repetición {repetition + 1}/{args.repetitions}")
            benchmarks = (("Secuencial", lambda: bench_sequential(points, queries)),)
            for technique, benchmark in benchmarks:
                row = {"tecnica": technique, "n_registros": size, "repeticion": repetition + 1}
                row.update(benchmark())
                runs.append(row)
            with tempfile.TemporaryDirectory(prefix="bd2-spatial-") as directory:
                row = {"tecnica": "R-Tree", "n_registros": size, "repeticion": repetition + 1}
                row.update(bench_rtree(points, queries, directory))
                runs.append(row)
            row = {"tecnica": "GiST (PostGIS)", "n_registros": size, "repeticion": repetition + 1}
            if args.sin_postgis:
                row.update({metric: _common.NA for metric in METRICS})
            else:
                try:
                    row.update(bench_gist(points, queries, args.postgis_dsn))
                except (OSError, RuntimeError) as exc:
                    _common.progress(f"GiST omitido: {exc}")
                    row.update({metric: _common.NA for metric in METRICS})
            runs.append(row)
    fields = ["tecnica", "n_registros", "repeticion", *METRICS]
    _common.write_csv(args.output_dir / "spatial_runs.csv", runs, fields)
    summary = _common.summarize(runs, ("tecnica", "n_registros"), METRICS)
    _common.write_csv(args.output_dir / "spatial_comparison.csv", summary,
                      ["tecnica", "n_registros", "repeticiones", *METRICS,
                       *[metric + "_std" for metric in METRICS]])
    try:
        for metric in ("tiempo_construccion_seg", "tiempo_rango_5km_seg", "tiempo_knn_10_seg"):
            _common.plot(args.output_dir / f"spatial_{metric}.png", f"Spatial: {metric}", "segundos",
                         [_common.series(summary, technique, metric) for technique in TECHNIQUES],
                         "GiST queda como NA cuando no se inicia PostGIS; memoria mide Python (tracemalloc).")
    except ModuleNotFoundError as exc:
        _common.progress(f"PNG omitidas: instala requirements.txt ({exc.name})")
    _common.write_metadata(args, "spatial", time.perf_counter() - started,
                           {"queries": args.queries, "radii_m": RADII_M, "ks": KS,
                            "postgis_requested": not args.sin_postgis})
    _common.print_table(summary, ("tecnica", "n_registros", "tiempo_construccion_seg", "tiempo_rango_5km_seg"))
    return summary


if __name__ == "__main__":
    main()
