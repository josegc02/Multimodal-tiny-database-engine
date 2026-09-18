"""Comparativa independiente de HeapFile y SequentialFile; una corrida por tamaño.

Ejemplo: python benchmarks/bench_storage.py --sizes 100 1000 5000
Sin argumentos ejecuta 1000, 10000 y 100000. No reorganiza antes de buscar.
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
from engine.storage.heap_file import HeapFile
from engine.storage.sequential_file import SequentialFile

FIELDS = ["tecnica", "n_registros", "tiempo_insercion_seg", "tiempo_busqueda_seg",
          "espacio_disco_bytes", "tiempo_reorganizacion_seg"]


def benchmark(n, seed=42):
    records = generate_records(n, seed)
    keys = random.Random(seed + 1).sample(range(n), 100)
    delete_keys = set(random.Random(seed + 2).sample(range(n), round(n * .35)))
    rows = []
    directory = tempfile.mkdtemp(prefix="bd2-storage-")
    try:
        for technique in ("HeapFile", "SequentialFile"):
            print(f"[storage] N={n}: {technique}", file=sys.stderr, flush=True)
            main = os.path.join(directory, technique + ".main")
            aux = os.path.join(directory, technique + ".aux")
            storage = (HeapFile(main, SCHEMA) if technique == "HeapFile" else
                       SequentialFile(main, aux, SCHEMA, key_field="id"))
            with storage:
                start = time.perf_counter()
                for record in records:
                    storage.insert(record)
                insert_seconds = time.perf_counter() - start

                # Mismas claves, mismo orden, resultados materializados en ambos motores.
                start = time.perf_counter()
                if technique == "HeapFile":
                    found = [storage.search_by_key("id", key) for key in keys]
                else:
                    found = [storage.search_by_key(key) for key in keys]
                search_seconds = time.perf_counter() - start
                if any(len(result) != 1 or result[0][1]["id"] != key for key, result in zip(keys, found)):
                    raise RuntimeError("La búsqueda no devolvió los registros esperados")
                size = os.path.getsize(main) + (os.path.getsize(aux) if technique == "SequentialFile" else 0)
                reorganize_seconds = "NA"
                if technique == "SequentialFile":
                    # Los RIDs devueltos durante inserción pueden haber cambiado.
                    # Este scan y las eliminaciones NO forman parte del tiempo de reorganización.
                    current_rids = [rid for rid, record in storage.scan() if record["id"] in delete_keys]
                    if len(current_rids) != len(delete_keys):
                        raise RuntimeError("Faltan claves a eliminar")
                    for rid in current_rids:
                        if not storage.delete(rid):
                            raise RuntimeError("No se pudo eliminar un RID actual")
                    if not storage.needs_reorganization():
                        raise RuntimeError("No se activó el umbral de reorganización tras eliminar el 35%")
                    start = time.perf_counter()
                    storage.reorganize()
                    reorganize_seconds = time.perf_counter() - start
                    remaining = [record["id"] for _, record in storage.scan()]
                    if remaining != [key for key in range(n) if key not in delete_keys]:
                        raise RuntimeError("La reorganización no conservó los registros activos en orden")
                rows.append(dict(zip(FIELDS, (technique, n, insert_seconds, search_seconds, size, reorganize_seconds))))
    finally:
        shutil.rmtree(directory)
    return rows


def main():
    args = arguments(__doc__)
    start = time.perf_counter()
    rows = [row for n in args.sizes for row in benchmark(n, args.seed)]
    save_results(rows, FIELDS, [
        ("tiempo_insercion_seg", "tiempo_insercion", "Inserción de N registros aleatorios", "Segundos"),
        ("tiempo_busqueda_seg", "tiempo_busqueda", "Búsqueda PK: total de 100 consultas", "Segundos"),
        ("espacio_disco_bytes", "espacio_disco", "Disco después de insertar, antes de eliminar", "Bytes en disco"),
    ], args, "storage", start, {"page_size": 4096, "equality_queries": 100, "deleted_fraction": .35,
                               "search_state": "Después de insertar, antes de reorganizar; caché del SO sin vaciar",
                               "space_state": "Antes de eliminar; main + aux para SequentialFile",
                               "reorganization": "Solo reorganize(); excluye scan, borrado y verificación"})


if __name__ == "__main__":
    main()

# Conclusiones medidas el 2026-09-18, semilla 42, una corrida, /tmp en tmpfs:
# 1. En N=100000, Heap insertó en 2.296409 s y Secuencial en 1459.402136 s:
#    el tiempo del Secuencial fue 635.51 veces el de Heap en esta carga aleatoria.
# 2. Las 100 búsquedas tardaron 21.079896 s (Heap) y 8.013247 s (Secuencial):
#    Heap consumió 2.63 veces el tiempo de búsqueda del Secuencial.
# 3. Ambos ocuparon 4141056 bytes antes de borrar; no hubo ventaja de espacio.
# 4. Tras borrar 35%, reorganize() tomó 0.374408 s; excluye el costo del borrado.
#    La corrida completa tomó 1513.480775 s. No son tiempos de un SSD físico.
