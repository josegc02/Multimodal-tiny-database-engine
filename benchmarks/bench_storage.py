"""Comparativa de rendimiento: Heap File vs Archivo Secuencial Paginado.

Mide:
- Tiempo de insercion (1k, 10k, 100k)
- Tiempo de busqueda por clave primaria
- Espacio en disco
- Tiempo de reorganizacion
"""

import csv
import gc
import os
import time
import uuid

from engine.storage.heap_file import HeapFile
from engine.storage.sequential_file import SequentialFile


RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
SCHEMA = [("id", "int"), ("nombre", "str", 20), ("saldo", "int")]


def cargar_csv(ruta):
    """Carga un CSV como lista de dicts."""
    with open(ruta, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [
            {"id": int(r["id"]), "nombre": r["nombre"], "saldo": int(r["saldo"])}
            for r in reader
        ]


def _ruta_unica(prefijo, extension=".db"):
    """Genera una ruta unica en results/ para evitar conflictos."""
    os.makedirs(RESULTS_DIR, exist_ok=True)
    sufijo = uuid.uuid4().hex[:8]
    return os.path.join(RESULTS_DIR, f"{prefijo}_{sufijo}{extension}")


def _borrar_silencioso(*rutas):
    """Borra archivos sin fallar si estan en uso."""
    for r in rutas:
        try:
            if os.path.exists(r):
                os.remove(r)
        except OSError:
            pass


def bench_heap(registros):
    """Mide tiempos de HeapFile."""
    ruta = _ruta_unica("bench_heap")
    storage = HeapFile(ruta, SCHEMA)

    try:
        # Insercion
        inicio = time.perf_counter()
        for r in registros:
            storage.insert(r)
        tiempo_insercion = time.perf_counter() - inicio

        # Busqueda
        inicio = time.perf_counter()
        for i in range(100):
            storage.search_by_key("id", i * (len(registros) // 100))
        tiempo_busqueda = time.perf_counter() - inicio

        # Espacio
        espacio = os.path.getsize(ruta)

    finally:
        storage.close()
        del storage
        gc.collect()
        _borrar_silencioso(ruta)

    return {
        "insercion": tiempo_insercion,
        "busqueda": tiempo_busqueda,
        "espacio": espacio,
    }


def bench_sequential(registros):
    """Mide tiempos de SequentialFile."""
    ruta_main = _ruta_unica("bench_seq_main")
    ruta_aux = _ruta_unica("bench_seq_aux")

    storage = SequentialFile(ruta_main, ruta_aux, SCHEMA, key_field="id")

    try:
        # Insercion
        inicio = time.perf_counter()
        for r in registros:
            storage.insert(r)
        tiempo_insercion = time.perf_counter() - inicio

        # Busqueda
        inicio = time.perf_counter()
        for i in range(100):
            storage.search_by_key(i * (len(registros) // 100))
        tiempo_busqueda = time.perf_counter() - inicio

        # Espacio
        espacio = os.path.getsize(ruta_main) + os.path.getsize(ruta_aux)

        # Reorganizacion
        necesita_reorg = storage.needs_reorganization()
        inicio = time.perf_counter()
        storage.reorganize()
        tiempo_reorg = time.perf_counter() - inicio

    finally:
        storage.close()
        del storage
        gc.collect()
        _borrar_silencioso(ruta_main, ruta_aux)

    return {
        "insercion": tiempo_insercion,
        "busqueda": tiempo_busqueda,
        "espacio": espacio,
        "reorganizacion": tiempo_reorg,
        "necesitaba": necesita_reorg,
    }


def main():
    for tamano in ["1k", "5k", "10k"]:
        print(f"\n=== Dataset {tamano} ===")
        ruta_csv = os.path.join(RESULTS_DIR, f"dataset_{tamano}.csv")

        if not os.path.exists(ruta_csv):
            print(f"  ERROR: no existe {ruta_csv}")
            print(f"  Ejecuta primero: python -m benchmarks.generate_datasets")
            continue

        registros = cargar_csv(ruta_csv)
        n = len(registros)
        print(f"  Registros: {n}")

        print("Heap File...")
        r_heap = bench_heap(registros)
        print(f"  Insercion: {r_heap['insercion']:.3f}s")
        print(f"  Busqueda: {r_heap['busqueda']:.3f}s")
        print(f"  Espacio: {r_heap['espacio']} bytes")

        print("Sequential File...")
        r_seq = bench_sequential(registros)
        print(f"  Insercion: {r_seq['insercion']:.3f}s")
        print(f"  Busqueda: {r_seq['busqueda']:.3f}s")
        print(f"  Espacio: {r_seq['espacio']} bytes")
        print(f"  Reorganizacion: {r_seq['reorganizacion']:.3f}s")


if __name__ == "__main__":
    main()