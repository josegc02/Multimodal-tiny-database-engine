"""Comparativa independiente de HeapFile y SequentialFile.

Ejemplo: python benchmarks/bench_storage.py --sizes 200 1000 5000 --repetitions 1
Sin argumentos ejecuta 1000, 10000 y 100000 con 3 repeticiones por tamaño.
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

from benchmarks._common import (NA, arguments, no_gc, plot, print_table, progress, read_summary, series,
                                summarize, write_csv, write_metadata)
from benchmarks.generate_datasets import SCHEMA, generate_records
from engine.storage.heap_file import HeapFile
from engine.storage.sequential_file import SequentialFile

METRICS = ["tiempo_insercion_seg", "tiempo_busqueda_seg", "tiempo_busqueda_post_reorg_seg",
           "espacio_disco_bytes", "espacio_post_reorg_bytes", "tiempo_reorganizacion_seg",
           "reorganizaciones_automaticas", "paginas_aux_tras_carga"]
FIELDS = ["tecnica", "n_registros", "repeticiones"] + [
    name for metric in METRICS for name in (metric, metric + "_std")]
QUERIES = 100


def _search(storage, technique, keys):
    if technique == "HeapFile":
        # Clave primaria: el heap puede detenerse en la primera coincidencia.
        return [storage.search_by_key("id", key, unique=True) for key in keys]
    return [storage.search_by_key(key) for key in keys]


def _timed_search(storage, technique, keys, expected):
    start = time.perf_counter()
    found = _search(storage, technique, keys)
    elapsed = time.perf_counter() - start
    if any(len(result) != 1 or result[0][1]["id"] != key for key, result in zip(keys, found)):
        raise RuntimeError(f"{technique}: la búsqueda no devolvió los registros esperados")
    if expected is not None and any(result[0][1] != expected[key] for key, result in zip(keys, found)):
        raise RuntimeError(f"{technique}: registro recuperado distinto del insertado")
    return elapsed


def benchmark(n, seed, repetition):
    records = generate_records(n, seed)
    by_key = {record["id"]: record for record in records}
    keys = random.Random(seed + 1).sample(range(n), QUERIES)
    delete_keys = set(random.Random(seed + 2).sample(range(n), round(n * .35)))
    survivors = [key for key in keys if key not in delete_keys]
    rows = []
    directory = tempfile.mkdtemp(prefix="bd2-storage-")
    try:
        for technique in ("HeapFile", "SequentialFile"):
            progress(f"[storage] N={n} rep={repetition}: {technique}")
            main = os.path.join(directory, technique + ".main")
            aux = os.path.join(directory, technique + ".aux")
            storage = (HeapFile(main, SCHEMA) if technique == "HeapFile" else
                       SequentialFile(main, aux, SCHEMA, key_field="id"))
            with storage:
                # 1. Inserción en orden aleatorio. En el secuencial incluye las
                #    reorganizaciones automáticas que dispara la propia carga.
                start = time.perf_counter()
                for record in records:
                    storage.insert(record)
                insert_seconds = time.perf_counter() - start

                # 2. 100 búsquedas por clave primaria, estado tras la carga.
                search_seconds = _timed_search(storage, technique, keys, by_key)
                size = os.path.getsize(main) + (os.path.getsize(aux) if technique == "SequentialFile" else 0)
                aux_after_load = storage.num_pages_aux if technique == "SequentialFile" else NA

                # 3. Borrar 35% (fuera del cronómetro) y reorganizar el secuencial.
                victims = [rid for rid, record in storage.scan() if record["id"] in delete_keys]
                for rid in victims:
                    if not storage.delete(rid):
                        raise RuntimeError("No se pudo eliminar un RID actual")
                reorganize_seconds, after_search, after_size, automatic, aux_pages = NA, NA, NA, NA, NA
                if technique == "SequentialFile":
                    automatic = storage.reorganizations
                    aux_pages = aux_after_load
                    if not storage.needs_reorganization():
                        raise RuntimeError("Borrar 35% no activó el umbral del 30%")
                    start = time.perf_counter()
                    storage.reorganize()
                    reorganize_seconds = time.perf_counter() - start
                    remaining = [key for _, key, _ in storage._iter_main_all()]
                    if remaining != sorted(set(range(n)) - delete_keys) or storage.num_pages_aux:
                        raise RuntimeError("La reorganización no conservó los registros activos en orden")
                    after_search = _timed_search(storage, technique, survivors, by_key) * QUERIES / len(survivors)
                    after_size = os.path.getsize(main) + os.path.getsize(aux)
                rows.append({"tecnica": technique, "n_registros": n,
                             "tiempo_insercion_seg": insert_seconds,
                             "tiempo_busqueda_seg": search_seconds,
                             "tiempo_busqueda_post_reorg_seg": after_search,
                             "espacio_disco_bytes": size,
                             "espacio_post_reorg_bytes": after_size,
                             "tiempo_reorganizacion_seg": reorganize_seconds,
                             "reorganizaciones_automaticas": automatic,
                             "paginas_aux_tras_carga": aux_pages})
    finally:
        shutil.rmtree(directory)
    return rows


def plots(rows, out):
    ms = 1000 / QUERIES  # total de 100 consultas -> ms por consulta
    us = 1_000_000
    plot(out / "storage_tiempo_insercion.png", "Inserción: costo por registro (orden aleatorio)",
         "Microsegundos por inserción",
         [series(rows, "HeapFile", "tiempo_insercion_seg", "HeapFile — O(1)", us, per="n"),
          series(rows, "SequentialFile", "tiempo_insercion_seg",
                 "SequentialFile — O(log N) + reorganizaciones amortizadas", us, per="n")],
         note="Tiempo total de N inserciones dividido por N. Curva plana = costo constante por operación.")
    plot(out / "storage_tiempo_busqueda.png", "Búsqueda por clave primaria (promedio de 100 consultas)",
         "Milisegundos por consulta",
         [series(rows, "HeapFile", "tiempo_busqueda_seg", "HeapFile (scan) — O(N)", ms),
          series(rows, "SequentialFile", "tiempo_busqueda_seg", "SequentialFile tras la carga — O(log N)", ms),
          series(rows, "SequentialFile", "tiempo_busqueda_post_reorg_seg",
                 "SequentialFile tras reorganizar — O(log N)", ms)],
         note="Heap: recorre páginas hasta la clave. Secuencial: búsqueda binaria en main; aux por índice en memoria.")
    plot(out / "storage_espacio_disco.png", "Espacio en disco", "Bytes",
         [series(rows, "HeapFile", "espacio_disco_bytes", "HeapFile tras la carga"),
          series(rows, "SequentialFile", "espacio_disco_bytes", "SequentialFile tras la carga (main + aux)"),
          series(rows, "SequentialFile", "espacio_post_reorg_bytes",
                 "SequentialFile tras borrar 35% y reorganizar")],
         note="El secuencial reserva 10% libre por página (fill_factor = 0,9). En 1K Heap y Secuencial coinciden.")
    plot(out / "storage_tiempo_reorganizacion.png",
         "Reorganización del secuencial tras borrar 35% de los registros", "Segundos",
         [series(rows, "SequentialFile", "tiempo_reorganizacion_seg", "SequentialFile.reorganize() — O(N)")],
         note="Merge de main (ordenado) con aux: lineal en el número de páginas. El Heap no se reorganiza.")


def main():
    args = arguments(__doc__)
    if args.solo_graficas:
        plots(read_summary(args.output_dir / "storage_comparison.csv"), args.output_dir)
        print(f"Gráficas regeneradas en {args.output_dir.resolve()}")
        return
    started = time.perf_counter()
    runs = []
    for n in args.sizes:
        for rep in range(1, args.repetitions + 1):
            with no_gc():
                runs.extend(benchmark(n, args.seed, rep))
    rows = summarize(runs, ("tecnica", "n_registros"), METRICS)
    os.makedirs(args.output_dir, exist_ok=True)
    write_csv(args.output_dir / "storage_comparison.csv", rows, FIELDS)
    write_csv(args.output_dir / "storage_runs.csv", runs, ["tecnica", "n_registros"] + METRICS)

    out = args.output_dir
    plots(rows, out)

    elapsed = time.perf_counter() - started
    write_metadata(args, "storage", elapsed, {
        "page_size": 4096, "equality_queries": QUERIES, "deleted_fraction": .35,
        "gc": "recolector cíclico desactivado durante cada tamaño (como timeit); gc.collect() antes de medir",
        "sequential": "auto_reorganize=True: reorganiza si desperdicio > 30% o aux > ceil(log2(P_main+1)) páginas; fill_factor 0,9",
        "heap_search": "search_by_key(unique=True): scan que se detiene en la primera coincidencia",
        "search_state": "tras la carga y, en el secuencial, también tras reorganizar (65 claves sobrevivientes, escalado a 100)",
        "space_state": "después de insertar; main + aux para SequentialFile",
        "reorganization": "solo reorganize(); excluye scan, borrado y verificación",
        "cache": "caché del sistema operativo sin vaciar"})
    print_table(rows, FIELDS)
    print(f"\nResultados: {out.resolve()}\nDuración completa: {elapsed:.3f} s")


if __name__ == "__main__":
    main()
