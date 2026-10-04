"""B+ agrupado, B+ no agrupado y hash dinámico sobre la misma tabla.

python benchmarks/bench_indexes.py --sizes 200 1000 5000 --repetitions 1

Todas las consultas devuelven REGISTROS COMPLETOS: el B+ agrupado los tiene en
sus hojas; el no agrupado y el hash resuelven cada RID en un HeapFile real.
Cada estructura usa el máximo de entradas que cabe en una página de 4096 B.
"""

import os
from pathlib import Path
import random
import shutil
import sys
import tempfile
import time

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmarks._common import (NA, arguments, no_gc, plot, print_table, progress, series,
                                summarize, write_csv, write_metadata)
from benchmarks.generate_datasets import SCHEMA, generate_records
from engine.indexes import BPlusTreeClustered, BPlusTreeUnclustered, ExtendibleHash
from engine.indexes.bplus_tree import CHILD_SIZE, NODE_HEADER_SIZE
from engine.query.external_algorithms import external_sort
from engine.storage.heap_file import HeapFile
from engine.storage.record import Schema

PAGE_SIZE = 4096
KEY_SIZE = 8  # id int64
RECORD_SIZE = Schema(SCHEMA).record_size
# Nodo interno: header + M*(hijo + clave) + último hijo. El no agrupado guarda el
# RID empaquetado (8 B) donde el interno guarda el hijo, así que usa el mismo M.
ORDER_UNCLUSTERED = (PAGE_SIZE - NODE_HEADER_SIZE - CHILD_SIZE) // (CHILD_SIZE + KEY_SIZE)
# Hoja agrupada: header + M*(clave + registro completo).
ORDER_CLUSTERED = min(ORDER_UNCLUSTERED, (PAGE_SIZE - NODE_HEADER_SIZE) // (KEY_SIZE + RECORD_SIZE))
# Bucket equivalente a una página con entradas (clave, RID) de 16 B.
HASH_BUCKET = ORDER_UNCLUSTERED

TECHNIQUES = ("B+ agrupado", "B+ no agrupado", "Extendible Hash")
METRICS = ["tiempo_construccion_seg", "tiempo_snapshot_seg", "tiempo_igualdad_seg", "tiempo_rango_seg",
           "tiempo_orden_seg",
           "espacio_total_bytes", "espacio_adicional_bytes", "memoria_estimada_bytes",
           "tiempo_actualizaciones_seg"]
FIELDS = ["tecnica", "n_registros", "repeticiones"] + [
    name for metric in METRICS for name in (metric, metric + "_std")]
EQUALITY_QUERIES, RANGE_QUERIES, RANGE_WIDTH, UPDATE_PAIRS = 100, 20, 100, 500


def retained_size(root):
    """Estimación del grafo Python retenido, sin duplicar referencias compartidas.

    No es RSS ni una medición del pico de memoria del proceso.
    """
    pending, seen, size = [root], set(), 0
    while pending:
        value = pending.pop()
        if id(value) in seen:
            continue
        seen.add(id(value))
        size += sys.getsizeof(value)
        if isinstance(value, dict):
            pending.extend(value.keys())
            pending.extend(value.values())
        elif isinstance(value, (list, tuple, set, frozenset)):
            pending.extend(value)
        elif hasattr(value, "__dict__"):
            pending.append(vars(value))
    return size


def _check(condition, message):
    if not condition:
        raise RuntimeError(message)


def benchmark(n, seed, repetition):
    records = generate_records(n, seed)
    keys = random.Random(seed + 1).sample(range(n), EQUALITY_QUERIES)
    rng = random.Random(seed + 2)
    ranges = [(start, min(n - 1, start + RANGE_WIDTH)) for start in (rng.randrange(n) for _ in range(RANGE_QUERIES))]
    updates = [{**record, "id": n + record["id"]} for record in generate_records(UPDATE_PAIRS, seed + 3)]
    rows, structures = [], []
    directory = tempfile.mkdtemp(prefix="bd2-indexes-")
    try:
        for technique in TECHNIQUES:
            progress(f"[indexes] N={n} rep={repetition}: {technique}")
            clustered = technique == "B+ agrupado"
            hashed = technique == "Extendible Hash"
            base = tempfile.mkdtemp(dir=directory)
            index_path = os.path.join(base, "index")
            heap_path = os.path.join(base, "table.heap")

            # Tabla base (no cronometrada): el agrupado ES la tabla.
            heap = None
            if not clustered:
                heap = HeapFile(heap_path, SCHEMA, page_size=PAGE_SIZE)
                entries = [(record["id"], heap.insert(record)) for record in records]
            index = (BPlusTreeClustered(index_path, SCHEMA, "id", M=ORDER_CLUSTERED, page_size=PAGE_SIZE) if clustered else
                     ExtendibleHash(bucket_capacity=HASH_BUCKET, filepath=index_path) if hashed else
                     BPlusTreeUnclustered(index_path, order=ORDER_UNCLUSTERED, page_size=PAGE_SIZE))
            try:
                fetch = (lambda rids: [heap.get(rid) for rid in rids]) if heap else None

                # 1. Construcción: N inserciones. La persistencia del hash (snapshot
                #    JSON completo, O(N)) se mide aparte para no mezclarla con el
                #    costo O(1) de cada inserción.
                start = time.perf_counter()
                if clustered:
                    inserted = sum(index.insert(record) for record in records)
                else:
                    inserted = sum(index.insert(key, rid) for key, rid in entries)
                construction = time.perf_counter() - start
                snapshot = NA
                if hashed:
                    start = time.perf_counter()
                    index.flush()
                    snapshot = time.perf_counter() - start
                _check(inserted == n, "No se insertaron todos los registros/pares")

                # 2. Igualdad: registro completo por clave.
                start = time.perf_counter()
                if clustered:
                    found = [[index.search(key)] for key in keys]
                else:
                    found = [fetch(index.search(key)) for key in keys]
                equality = time.perf_counter() - start
                _check(all([r["id"] for r in result] == [key] for key, result in zip(keys, found)),
                       "Resultados de igualdad incorrectos")

                # 3. Rango [k, k+100]: registros completos en orden de clave.
                range_seconds = NA
                if not hashed:
                    start = time.perf_counter()
                    found = [index.range_search(low, high) if clustered else fetch(index.range_search(low, high))
                             for low, high in ranges]
                    range_seconds = time.perf_counter() - start
                    for (low, high), result in zip(ranges, found):
                        _check([r["id"] for r in result] == list(range(low, high + 1)),
                               "Resultados de rango incorrectos")

                # 4. Ordenamiento (ORDER BY id) de toda la tabla.
                #    Hash no puede aportar orden: se mide lo que haría el motor
                #    (scan del heap + external sort k-way), marcado en la gráfica.
                start = time.perf_counter()
                if clustered:
                    ordered = list(index.scan())
                elif hashed:
                    ordered = list(external_sort((record for _, record in heap.scan()), "id"))
                else:
                    ordered = fetch(index.iter_ordered())
                order_seconds = time.perf_counter() - start
                _check([r["id"] for r in ordered] == list(range(n)), "ORDER BY incorrecto")

                # 5. Espacio: tabla + índice, y lo que se agrega sobre un heap con los mismos datos.
                index_bytes = os.path.getsize(index_path)
                heap_bytes = os.path.getsize(heap_path) if heap else None
                total = index_bytes if clustered else heap_bytes + index_bytes
                memory = retained_size(index) if hashed else NA
                if hashed:
                    structures.append({"tecnica": technique, "n_registros": n, **index.stats()})
                else:
                    tree = index if clustered else index.tree
                    structures.append({"tecnica": technique, "n_registros": n, "M": tree.header.M,
                                       "allocated_node_pages": tree.header.number_pages - 1})

                # 6. 500 ciclos inserción + eliminación de tabla e índice.
                start = time.perf_counter()
                inserted = deleted = 0
                for record in updates:
                    if clustered:
                        inserted += index.insert(record)
                        deleted += index.delete(record["id"])
                    else:
                        rid = heap.insert(record)
                        inserted += index.insert(record["id"], rid)
                        deleted += bool(index.delete(record["id"], rid))
                        heap.delete(rid)
                changes = time.perf_counter() - start
                if hashed:
                    index.flush()  # fuera del cronómetro: ya se midió en tiempo_snapshot_seg
                _check(inserted == UPDATE_PAIRS and deleted == UPDATE_PAIRS, "Falló el ciclo inserción/eliminación")
                _check(not any(index.search(record["id"]) for record in updates), "Quedaron claves temporales")

                rows.append({"tecnica": technique, "n_registros": n,
                             "tiempo_construccion_seg": construction, "tiempo_snapshot_seg": snapshot,
                             "tiempo_igualdad_seg": equality,
                             "tiempo_rango_seg": range_seconds, "tiempo_orden_seg": order_seconds,
                             "espacio_total_bytes": total, "espacio_adicional_bytes": NA,
                             "memoria_estimada_bytes": memory, "tiempo_actualizaciones_seg": changes,
                             "_heap_bytes": heap_bytes})
            finally:
                index.close()
                if heap:
                    heap.close()
        # Espacio adicional respecto del heap con los mismos N registros.
        heap_reference = next(row["_heap_bytes"] for row in rows if row["_heap_bytes"])
        for row in rows:
            row["espacio_adicional_bytes"] = row["espacio_total_bytes"] - heap_reference
            del row["_heap_bytes"]
    finally:
        shutil.rmtree(directory)
    return rows, structures


def main():
    args = arguments(__doc__)
    started = time.perf_counter()
    runs, structures = [], []
    for n in args.sizes:
        for rep in range(1, args.repetitions + 1):
            with no_gc():
                result, stats = benchmark(n, args.seed, rep)
            runs.extend(result)
            if rep == 1:
                structures.extend(stats)
    rows = summarize(runs, ("tecnica", "n_registros"), METRICS)
    os.makedirs(args.output_dir, exist_ok=True)
    write_csv(args.output_dir / "indexes_comparison.csv", rows, FIELDS)
    write_csv(args.output_dir / "indexes_runs.csv", runs, ["tecnica", "n_registros"] + METRICS)

    out = args.output_dir
    us = 1_000_000
    all_three = lambda metric, scale=1.0, per=None: [series(rows, t, metric, scale=scale, per=per) for t in TECHNIQUES]
    plot(out / "indexes_tiempo_construccion.png", "Construcción del índice: costo por inserción",
         "Microsegundos por inserción",
         [series(rows, "B+ agrupado", "tiempo_construccion_seg", "B+ agrupado — O(log N)", us, per="n"),
          series(rows, "B+ no agrupado", "tiempo_construccion_seg", "B+ no agrupado — O(log N)", us, per="n"),
          series(rows, "Extendible Hash", "tiempo_construccion_seg", "Extendible Hash — O(1) amortizado", us, per="n")],
         note="Tiempo total de N inserciones dividido por N. El snapshot del hash se reporta aparte (tiempo_snapshot_seg).")
    plot(out / "indexes_tiempo_igualdad.png", "Búsqueda por igualdad (promedio de 100, registro completo)",
         "Milisegundos por consulta",
         [series(rows, "B+ agrupado", "tiempo_igualdad_seg", "B+ agrupado — O(log N)", 1000, per=EQUALITY_QUERIES),
          series(rows, "B+ no agrupado", "tiempo_igualdad_seg", "B+ no agrupado — O(log N) + 1 lectura", 1000,
                 per=EQUALITY_QUERIES),
          series(rows, "Extendible Hash", "tiempo_igualdad_seg", "Extendible Hash — O(1)", 1000, per=EQUALITY_QUERIES)])
    plot(out / "indexes_tiempo_rango.png", "Búsqueda por rango de 101 claves (promedio de 20, registros completos)",
         "Milisegundos por consulta",
         [series(rows, "B+ agrupado", "tiempo_rango_seg", "B+ agrupado — O(log N + k)", 1000, per=RANGE_QUERIES),
          series(rows, "B+ no agrupado", "tiempo_rango_seg", "B+ no agrupado — O(log N + k lecturas)", 1000,
                 per=RANGE_QUERIES)],
         note="k = 101 filas por rango. Extendible Hash no soporta rangos. El no agrupado lee cada RID del heap.")
    plot(out / "indexes_tiempo_orden.png", "Ordenamiento: ORDER BY id sobre toda la tabla", "Segundos",
         [series(rows, "B+ agrupado", "tiempo_orden_seg", "B+ agrupado (hojas) — O(N)"),
          series(rows, "B+ no agrupado", "tiempo_orden_seg", "B+ no agrupado (hojas + RIDs) — O(N)"),
          series(rows, "Extendible Hash", "tiempo_orden_seg", "Hash: no aplica, scan + external sort — O(N log N)")],
         note="Tiempo total: recorrer N registros es O(N) (pendiente 1 en log-log).")
    plot(out / "indexes_espacio_total.png", "Espacio en disco: tabla + índice", "Bytes",
         all_three("espacio_total_bytes"),
         note="Agrupado: un solo archivo con los datos en las hojas. No agrupado y hash: heap + archivo del índice.")
    plot(out / "indexes_espacio_adicional.png", "Espacio adicional requerido por el índice", "Bytes",
         all_three("espacio_adicional_bytes"),
         note="Espacio total menos el de un heap con los mismos N registros. Crece O(N) en las tres estructuras.")
    plot(out / "indexes_tiempo_actualizaciones.png", "Inserciones y eliminaciones frecuentes: costo por operación",
         "Microsegundos por operación",
         [series(rows, "B+ agrupado", "tiempo_actualizaciones_seg", "B+ agrupado — O(log N)", us, per=2 * UPDATE_PAIRS),
          series(rows, "B+ no agrupado", "tiempo_actualizaciones_seg", "B+ no agrupado — O(log N)", us,
                 per=2 * UPDATE_PAIRS),
          series(rows, "Extendible Hash", "tiempo_actualizaciones_seg", "Extendible Hash — O(1)", us,
                 per=2 * UPDATE_PAIRS)],
         note="500 inserciones + 500 eliminaciones en tabla e índice. Sin el snapshot del hash.")
    for stale in ("indexes_espacio_disco.png", "indexes_memoria.png"):
        (out / stale).unlink(missing_ok=True)

    elapsed = time.perf_counter() - started
    write_metadata(args, "indexes", elapsed, {
        "page_size": PAGE_SIZE, "bplus_clustered_M": ORDER_CLUSTERED, "bplus_unclustered_M": ORDER_UNCLUSTERED,
        "gc": "recolector cíclico desactivado durante cada tamaño (como timeit); gc.collect() antes de medir",
        "hash_bucket_capacity": HASH_BUCKET, "hash_max_depth": 16,
        "equality_queries": EQUALITY_QUERIES, "range_queries": RANGE_QUERIES,
        "range_width": f"[k, min(N-1, k+{RANGE_WIDTH})]", "update_pairs": UPDATE_PAIRS,
        "results": "todas las consultas devuelven registros completos (no agrupado y hash leen el heap)",
        "ordering": "agrupado: hojas; no agrupado: hojas + heap.get; hash: heap.scan + external_sort",
        "space": "espacio_total = tabla + índice; espacio_adicional = total - heap con los mismos N registros",
        "memory_estimate": "solo hash: sys.getsizeof del grafo retenido; no RSS",
        "durability": "B+ escribe/flush por operación; hash en RAM, su snapshot JSON se mide aparte (tiempo_snapshot_seg)",
        "structural_stats": structures})
    print_table(rows, FIELDS)
    print(f"\nResultados: {out.resolve()}\nDuración completa: {elapsed:.3f} s")


if __name__ == "__main__":
    main()
