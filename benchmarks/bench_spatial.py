"""Comparación experimental de la Parte 2: búsqueda secuencial vs R-Tree vs GiST (PostGIS).

Ejemplos:
    python -m benchmarks.bench_spatial                    # 1K, 10K y 100K, 100 consultas, 3 repeticiones
    python -m benchmarks.bench_spatial --sin-postgis      # sin PostgreSQL
    python -m benchmarks.bench_spatial --sizes 1000 --queries 10 --repetitions 1 --sin-postgis

Reglas para que la comparación sea justa:
- Los puntos viven en un HeapFile en disco. La búsqueda secuencial lo recorre;
  el R-Tree devuelve RIDs y lee esos registros del heap; GiST consulta su tabla.
- Distancia Haversine (esfera) en las tres técnicas; PostGIS sobre la esfera.
- La construcción del R-Tree se cronometra sin tracemalloc; la memoria se mide
  en una pasada aparte. En GiST solo se cronometra CREATE INDEX (no la carga).
- Cada técnica se verifica fuera del cronómetro contra la búsqueda secuencial.
"""

from __future__ import annotations

import argparse
import heapq
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import tracemalloc

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmarks import _common
from benchmarks._common import NA
from benchmarks.generate_spatial_datasets import generate_points, generate_queries
from engine.indexes.rtree import RTree
from engine.spatial.distance import haversine
from engine.spatial.geometry import Point
from engine.storage.heap_file import HeapFile

TECHNIQUES = ("Secuencial", "R-Tree", "GiST (PostGIS)")
RADII_M = (1_000, 5_000, 10_000)
KS = (10, 50, 100)
POSTGIS_DSN = "postgresql://bd2:bd2@localhost:5433/espacial"
SCHEMA = [("id", "int"), ("ubicacion", "point")]

RANGE_METRICS = [f"tiempo_rango_{r // 1000}km_seg" for r in RADII_M]
KNN_METRICS = [f"tiempo_knn_{k}_seg" for k in KS]
METRICS = (["tiempo_construccion_seg"] + RANGE_METRICS + KNN_METRICS
           + ["espacio_indice_bytes", "memoria_pico_bytes",
              "nodos_visitados_rango", "nodos_visitados_knn"]
           + [f"resultados_rango_{r // 1000}km" for r in RADII_M])


def _timed(action):
    started = time.perf_counter()
    result = action()
    return time.perf_counter() - started, result


def _distances(pairs):
    return sorted(d for _, d in pairs)


def _same_knn(pairs, reference):
    """Compara k-NN por sus distancias (tolerancia de 1 mm), sin depender del desempate entre iguales."""
    found = _distances(pairs)
    return len(found) == len(reference) and all(abs(a - b) <= 1e-3 for a, b in zip(found, reference))


def build_heap(points, directory):
    heap = HeapFile(os.path.join(directory, "puntos.heap"), SCHEMA)
    rids = {}
    for row in points:
        rids[row["id"]] = heap.insert({"id": row["id"], "ubicacion": row["ubicacion"]})
    return heap, rids


# --- Búsqueda secuencial ---------------------------------------------------------------

def sequential_range(heap, center, radius):
    return [record["id"] for _, record in heap.scan() if haversine(center, record["ubicacion"]) <= radius]


def sequential_knn(heap, center, k):
    return heapq.nsmallest(k, ((record["id"], haversine(center, record["ubicacion"]))
                               for _, record in heap.scan()), key=lambda pair: (pair[1], pair[0]))


def bench_sequential(heap, centers):
    """Devuelve las mediciones y los resultados, que sirven de referencia para las otras técnicas."""
    row = {"tiempo_construccion_seg": NA, "espacio_indice_bytes": NA, "memoria_pico_bytes": NA,
           "nodos_visitados_rango": NA, "nodos_visitados_knn": NA}
    expected = {}
    for radius in RADII_M:
        elapsed, found = _timed(lambda: [sequential_range(heap, c, radius) for c in centers])
        row[f"tiempo_rango_{radius // 1000}km_seg"] = elapsed / len(centers)
        row[f"resultados_rango_{radius // 1000}km"] = sum(map(len, found)) / len(centers)
        expected[("rango", radius)] = [set(ids) for ids in found]
    for k in KS:
        elapsed, found = _timed(lambda: [sequential_knn(heap, c, k) for c in centers])
        row[f"tiempo_knn_{k}_seg"] = elapsed / len(centers)
        expected[("knn", k)] = [_distances(pairs) for pairs in found]
    return row, expected


# --- R-Tree propio -----------------------------------------------------------------------

def _build_rtree(path, points, rids):
    tree = RTree(path)
    for row in points:
        tree.insert(row["ubicacion"], rids[row["id"]])
    tree.flush()
    return tree


def rtree_memory(points, rids, directory):
    """Pico de memoria de Python al construir el árbol (pasada aparte: tracemalloc lo hace ~5 veces más lento)."""
    path = os.path.join(directory, "memoria.rtree")
    tracemalloc.start()
    try:
        _build_rtree(path, points, rids).close()
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
        os.remove(path)


def bench_rtree(heap, points, rids, centers, expected, directory, memory):
    path = os.path.join(directory, "puntos.rtree")
    build, tree = _timed(lambda: _build_rtree(path, points, rids))
    row = {"tiempo_construccion_seg": build, "espacio_indice_bytes": os.path.getsize(path),
           "memoria_pico_bytes": memory}

    def records(found):
        return [heap.get(rid) for _, rid, _ in found]

    try:
        nodes = []
        for radius in RADII_M:
            elapsed, _ = _timed(lambda: [records(tree.range_query(c, radius)) for c in centers])
            row[f"tiempo_rango_{radius // 1000}km_seg"] = elapsed / len(centers)
            for c, reference in zip(centers, expected[("rango", radius)]):
                found = {record["id"] for record in records(tree.range_query(c, radius))}
                assert found == reference, f"R-Tree difiere del secuencial (radio {radius} m)"
                nodes.append(tree.last_stats.nodes_visited)
        row["nodos_visitados_rango"] = sum(nodes) / len(nodes)

        nodes = []
        for k in KS:
            elapsed, _ = _timed(lambda: [records(tree.knn(c, k)) for c in centers])
            row[f"tiempo_knn_{k}_seg"] = elapsed / len(centers)
            for c, reference in zip(centers, expected[("knn", k)]):
                found = tree.knn(c, k)
                assert _same_knn([(rid, d) for _, rid, d in found], reference), f"R-Tree difiere en k-NN (k={k})"
                nodes.append(tree.last_stats.nodes_visited)
        row["nodos_visitados_knn"] = sum(nodes) / len(nodes)
        return row
    finally:
        tree.close()


# --- GiST (PostGIS) --------------------------------------------------------------------

def bench_gist(points, centers, expected, dsn):
    from postgis.client import build_index, connect, index_size, load_points, nearest_query, range_query

    connection = connect(dsn)
    try:
        load_points(connection, points)
        build, _ = _timed(lambda: build_index(connection))
        row = {"tiempo_construccion_seg": build, "espacio_indice_bytes": index_size(connection),
               "memoria_pico_bytes": NA, "nodos_visitados_rango": NA, "nodos_visitados_knn": NA}
        for radius in RADII_M:
            elapsed, found = _timed(lambda: [range_query(connection, c, radius) for c in centers])
            row[f"tiempo_rango_{radius // 1000}km_seg"] = elapsed / len(centers)
            for ids, reference in zip(found, expected[("rango", radius)]):
                assert set(ids) == reference, f"GiST difiere del secuencial (radio {radius} m)"
        for k in KS:
            elapsed, found = _timed(lambda: [nearest_query(connection, c, k) for c in centers])
            row[f"tiempo_knn_{k}_seg"] = elapsed / len(centers)
            for pairs, reference in zip(found, expected[("knn", k)]):
                assert _same_knn(pairs, reference), f"GiST difiere en k-NN (k={k})"
        return row
    finally:
        connection.close()


# --- Corrida -----------------------------------------------------------------------------

def _arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sizes", type=int, nargs="+", default=list(_common.OFFICIAL_SIZES))
    parser.add_argument("--queries", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--output-dir", type=Path, default=_common.RESULTS)
    parser.add_argument("--sin-postgis", action="store_true", help="no medir GiST (queda NA)")
    parser.add_argument("--postgis-dsn", default=POSTGIS_DSN)
    parser.add_argument("--solo-graficas", action="store_true",
                        help="no mide: redibuja las PNG desde spatial_comparison.csv")
    args = parser.parse_args(argv)
    if any(size < 1 for size in args.sizes) or len(set(args.sizes)) != len(args.sizes):
        parser.error("--sizes debe contener enteros positivos distintos")
    if args.queries < 1 or args.repetitions < 1:
        parser.error("--queries y --repetitions deben ser positivos")
    args.sizes = sorted(args.sizes)
    return args


def plots(rows, out):
    ms = 1000
    _common.plot(out / "spatial_tiempo_construccion.png", "Construcción del índice espacial", "Segundos",
                 [_common.series(rows, t, "tiempo_construccion_seg") for t in TECHNIQUES[1:]],
                 note="R-Tree: inserción punto por punto en disco. GiST: solo CREATE INDEX (datos ya cargados).")
    for radius in RADII_M:
        metric = f"tiempo_rango_{radius // 1000}km_seg"
        _common.plot(out / f"spatial_tiempo_rango_{radius // 1000}km.png",
                     f"Consulta por rango: radio de {radius // 1000} km (promedio de las consultas)",
                     "Milisegundos por consulta", [_common.series(rows, t, metric, scale=ms) for t in TECHNIQUES],
                     note="Secuencial: scan del heap O(N). R-Tree y GiST: filtro por MBR + distancia exacta.")
    for k in KS:
        metric = f"tiempo_knn_{k}_seg"
        _common.plot(out / f"spatial_tiempo_knn_{k}.png", f"Consulta k-NN: k = {k} (promedio de las consultas)",
                     "Milisegundos por consulta", [_common.series(rows, t, metric, scale=ms) for t in TECHNIQUES],
                     note="Secuencial: scan + heap de k. R-Tree: best-first por MINDIST. GiST: ORDER BY <-> LIMIT k.")
    _common.plot(out / "spatial_espacio_indice.png", "Espacio en disco del índice", "Bytes",
                 [_common.series(rows, t, "espacio_indice_bytes") for t in TECHNIQUES[1:]],
                 note="R-Tree: archivo de páginas de 4 KB. GiST: pg_relation_size del índice.")


def main(argv=None):
    args = _arguments(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if args.solo_graficas:
        plots(_common.read_summary(args.output_dir / "spatial_comparison.csv"), args.output_dir)
        return None

    started = time.perf_counter()
    runs = []
    queries = generate_queries(args.queries, args.seed + 1)
    centers = [Point(q["lat"], q["lon"]) for q in queries]
    for size in args.sizes:
        points = generate_points(size, args.seed)
        directory = tempfile.mkdtemp(prefix="bd2-spatial-")
        try:
            heap, rids = build_heap(points, directory)
            _common.progress(f"[spatial] N={size}: memoria del R-Tree")
            memory = rtree_memory(points, rids, directory)
            for repetition in range(1, args.repetitions + 1):
                base = {"n_registros": size, "repeticion": repetition}
                _common.progress(f"[spatial] N={size} rep={repetition}: Secuencial")
                row, expected = bench_sequential(heap, centers)
                runs.append({"tecnica": "Secuencial", **base, **row})

                _common.progress(f"[spatial] N={size} rep={repetition}: R-Tree")
                row = bench_rtree(heap, points, rids, centers, expected, directory, memory)
                runs.append({"tecnica": "R-Tree", **base, **row,
                             **{m: runs[-1][m] for m in METRICS if m.startswith("resultados_")}})
                os.remove(os.path.join(directory, "puntos.rtree"))

                gist = {metric: NA for metric in METRICS}
                if not args.sin_postgis:
                    _common.progress(f"[spatial] N={size} rep={repetition}: GiST")
                    gist.update(bench_gist(points, centers, expected, args.postgis_dsn))
                runs.append({"tecnica": "GiST (PostGIS)", **base, **gist,
                             **{m: runs[-2][m] for m in METRICS if m.startswith("resultados_")}})
            heap.close()
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    fields = ["tecnica", "n_registros", "repeticion", *METRICS]
    _common.write_csv(args.output_dir / "spatial_runs.csv", runs, fields)
    summary = _common.summarize(runs, ("tecnica", "n_registros"), METRICS)
    _common.write_csv(args.output_dir / "spatial_comparison.csv", summary,
                      ["tecnica", "n_registros", "repeticiones"]
                      + [name for metric in METRICS for name in (metric, metric + "_std")])
    plots(summary, args.output_dir)
    _common.write_metadata(args, "spatial", time.perf_counter() - started, {
        "queries": args.queries, "radii_m": RADII_M, "ks": KS, "postgis": not args.sin_postgis,
        "distance": "Haversine (esfera R = 6.371.008,8 m); PostGIS con ST_DWithin(..., false) y <->",
        "sequential": "scan de un HeapFile en disco calculando la distancia exacta",
        "rtree": "M = 177/113, split cuadrático; los resultados se leen del mismo HeapFile",
        "gist": "construcción = CREATE INDEX + ANALYZE con la tabla ya cargada; espacio = pg_relation_size",
        "memory": "R-Tree: pico de tracemalloc al construir, medido en una pasada aparte; GiST: NA (memoria del servidor)",
        "verification": "rango por ids y k-NN por distancias (tolerancia 1 mm) contra el secuencial, fuera del cronómetro",
    })
    _common.print_table(summary, ["tecnica", "n_registros", "tiempo_construccion_seg",
                                  "tiempo_rango_5km_seg", "tiempo_knn_10_seg"])
    return summary


if __name__ == "__main__":
    main()
