"""B+ agrupado/no agrupado y hash dinámico, con sus interfaces reales.

python benchmarks/bench_indexes.py --sizes 100 1000 5000
El agrupado guarda registros completos; los otros devuelven RIDs sintéticos.
No se mide la recuperación posterior desde un heap, ni el snapshot del hash.
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

from benchmarks._common import arguments, save_results
from benchmarks.generate_datasets import SCHEMA, generate_records
from engine.indexes import BPlusTreeClustered, BPlusTreeUnclustered, ExtendibleHash
from engine.storage.record import RID, Schema

ORDER = 64  # Misma capacidad lógica; cada formato tiene diferente tamaño de entrada.
FIELDS = ["tecnica", "n_registros", "tiempo_construccion_seg", "tiempo_igualdad_seg",
          "tiempo_rango_seg", "espacio_disco_bytes", "espacio_adicional_disco_bytes",
          "memoria_estimada_bytes", "tiempo_actualizaciones_seg"]


def retained_size(root):
    """Estimación del grafo Python retenido, sin duplicar referencias compartidas.

    Incluye objetos de claves y RIDs aunque el dataset también los referencie.
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


def synthetic_rid(key):
    return RID(page_id=key // 100, slot_id=key % 100)


def benchmark(n, seed=42):
    records = generate_records(n, seed)
    entries = [(record["id"], synthetic_rid(record["id"])) for record in records]
    keys = random.Random(seed + 1).sample(range(n), 100)
    rng = random.Random(seed + 2)
    ranges = [(start, min(n - 1, start + 100)) for start in (rng.randrange(n) for _ in range(20))]
    updates = [{**record, "id": n + record["id"]} for record in generate_records(500, seed + 3)]
    update_entries = [(record["id"], synthetic_rid(record["id"])) for record in updates]
    rows, structures = [], []
    directory = tempfile.mkdtemp(prefix="bd2-indexes-")
    try:
        for technique in ("B+ agrupado", "B+ no agrupado", "Extendible Hash"):
            print(f"[indexes] N={n}: {technique}", file=sys.stderr, flush=True)
            path = os.path.join(directory, technique + ".bpt")
            clustered = technique == "B+ agrupado"
            hashed = technique == "Extendible Hash"
            index = (BPlusTreeClustered(path, SCHEMA, "id", M=ORDER) if clustered else
                     ExtendibleHash(bucket_capacity=ORDER) if hashed else
                     BPlusTreeUnclustered(path, order=ORDER))
            with index:
                start = time.perf_counter()
                if clustered:
                    inserted = sum(index.insert(record) for record in records)
                else:
                    inserted = sum(index.insert(key, rid) for key, rid in entries)
                construction = time.perf_counter() - start
                if inserted != n:
                    raise RuntimeError("No se insertaron todos los registros/pares")
                start = time.perf_counter()
                found = [index.search(key) for key in keys]
                equality = time.perf_counter() - start
                if clustered:
                    valid = all(record is not None and record["id"] == key for key, record in zip(keys, found))
                else:
                    valid = all(result == [synthetic_rid(key)] for key, result in zip(keys, found))
                if not valid:
                    raise RuntimeError("Resultados de igualdad incorrectos")

                # Extendible Hash NO soporta rangos por diseño. NA es 'no soportado', no tiempo cero.
                range_seconds = "NA"
                if not hashed:
                    start = time.perf_counter()
                    found = [index.range_search(low, high) for low, high in ranges]
                    range_seconds = time.perf_counter() - start
                    for (low, high), result in zip(ranges, found):
                        actual = [r["id"] for r in result] if clustered else [r.page_id * 100 + r.slot_id for r in result]
                        if actual != list(range(low, high + 1)):
                            raise RuntimeError("Resultados de rango incorrectos")

                # Espacio medido después de construir, antes de las actualizaciones.
                if hashed:
                    disk, extra, memory = "NA", "NA", retained_size(index)
                    structures.append({"tecnica": technique, "n_registros": n, **index.stats()})
                else:
                    disk = os.path.getsize(path)
                    extra = disk - n * Schema(SCHEMA).record_size if clustered else disk
                    memory = "NA"  # No equivale a cero: no se mide caché/RSS del B+.
                    tree = index if clustered else index.tree
                    structures.append({"tecnica": technique, "n_registros": n,
                                       "allocated_node_pages": tree.header.number_pages - 1})

                start = time.perf_counter()
                inserted, deleted = 0, 0
                if clustered:
                    for record in updates:
                        inserted += index.insert(record)
                        deleted += index.delete(record["id"])
                else:
                    for key, rid in update_entries:
                        inserted += index.insert(key, rid)
                        deleted += index.delete(key, rid)
                changes = time.perf_counter() - start
                if inserted != 500 or deleted != 500:
                    raise RuntimeError("Falló el ciclo de 500 inserciones/eliminaciones")
                if any(index.search(record["id"]) for record in updates):
                    raise RuntimeError("Quedaron claves temporales después de eliminarlas")
                if any(not index.search(key) for key in keys):
                    raise RuntimeError("Las actualizaciones eliminaron claves originales")
                rows.append(dict(zip(FIELDS, (technique, n, construction, equality, range_seconds,
                                               disk, extra, memory, changes))))
    finally:
        shutil.rmtree(directory)
    return rows, structures


def main():
    args = arguments(__doc__)
    start = time.perf_counter()
    rows, structures = [], []
    for n in args.sizes:
        result, stats = benchmark(n, args.seed)
        rows.extend(result)
        structures.extend(stats)
    save_results(rows, FIELDS, [
        ("tiempo_construccion_seg", "tiempo_construccion", "Construcción de N entradas/registros", "Segundos"),
        ("tiempo_igualdad_seg", "tiempo_igualdad", "Igualdad: total de 100 búsquedas", "Segundos"),
        ("tiempo_rango_seg", "tiempo_rango", "Total de 20 rangos; Hash no soportado (NA)", "Segundos"),
        ("espacio_disco_bytes", "espacio_disco", "Disco: agrupado incluye datos; Hash en RAM (NA)", "Bytes en disco"),
        ("espacio_adicional_disco_bytes", "espacio_adicional", "Disco menos datos del agrupado; Hash en RAM (NA)", "Bytes adicionales"),
        ("memoria_estimada_bytes", "memoria", "Hash: memoria Python retenida estimada (B+ no medido)", "Bytes estimados"),
        ("tiempo_actualizaciones_seg", "tiempo_actualizaciones", "500 ciclos insert/delete (1000 operaciones)", "Segundos"),
    ], args, "indexes", start, {"page_size": 4096, "bplus_max_keys": ORDER, "hash_bucket_capacity": ORDER,
                               "hash_max_depth": 16, "equality_queries": 100, "range_queries": 20,
                               "range_width": "[k, min(N-1, k+100)], hasta 101 claves", "update_pairs": 500,
                               "space_state": "Antes de actualizaciones; agrupado incluye registros completos",
                               "extra_disk": "Agrupado: archivo - N*36; no agrupado: archivo completo",
                               "memory_estimate": "sys.getsizeof del grafo retenido del hash, referencias únicas; no RSS",
                               "NA": "Rango de Hash no soportado; disco de Hash no persistido; RAM B+ no medida",
                               "durability": "B+ escribe/flush; Hash en memoria, sin snapshot. Ninguno fuerza fsync",
                               "structural_stats": structures})


if __name__ == "__main__":
    main()

# Conclusiones de la corrida oficial: se completan después de medir los CSV reales.
