"""HNSW frente a búsqueda exacta según el tamaño del catálogo.

Uso, desde la raíz (después de ``python -m benchmarks.tienda.medir``)::

    python -m benchmarks.tienda.hnsw_escala

Catálogos de 8k, 25k y 50k vectores MobileNet: los 7,995 reales más copias con ruido
(cada copia es un vector real más ruido gaussiano, normalizado), para conservar la
distribución real. HNSW del motor con la configuración de la app (M=8,
ef_construction=50). 200 consultas al azar entre los vectores reales.
"""
import json
import random
import time
from pathlib import Path

import numpy as np

from benchmarks.tienda.medir import CACHE
from engine.indexes.hnsw import HNSWIndex

SALIDA = Path(__file__).with_name("hnsw_escala.json")
TAMANOS = (8_000, 25_000, 50_000)
CONSULTAS, FILA_POR_FILA = 200, 20
RUIDO = 0.8  # coseno copia-original 0.78: como el 10.º vecino real (0.79), no un clon
BUSQUEDAS = [(10, 50), (102, 102)]


def catalogo(reales, n, rnd):
    if n <= len(reales):
        return reales[:n]
    copias = reales[rnd.integers(0, len(reales), n - len(reales))]
    ruido = rnd.normal(size=copias.shape)
    ruido *= RUIDO / np.linalg.norm(ruido, axis=1, keepdims=True)
    copias = copias + ruido
    return np.vstack([reales, copias / np.linalg.norm(copias, axis=1, keepdims=True)])


def main():
    v = np.load(CACHE / "mobilenet.npy").astype(np.float64)
    v = v[np.linalg.norm(v, axis=1) > 0]
    reales = v / np.linalg.norm(v, axis=1, keepdims=True)
    rnd = np.random.default_rng(42)
    filas = []
    for n in TAMANOS:
        base = catalogo(reales, n, rnd)
        consultas = random.Random(5).sample(range(len(reales)), CONSULTAS)
        exacta, t = {}, time.perf_counter()
        for q in consultas:
            sim = base @ base[q]
            top = np.argpartition(-sim, 103)[:103]
            exacta[q] = [int(i) for i in top[np.argsort(-sim[top])] if i != q][:102]
        ms_numpy = (time.perf_counter() - t) / CONSULTAS * 1000
        t = time.perf_counter()
        for q in consultas[:FILA_POR_FILA]:
            puntos = [float(np.dot(base[i], base[q])) for i in range(len(base))]
            sorted(range(len(base)), key=lambda i: -puntos[i])[:102]
        ms_fila = (time.perf_counter() - t) / FILA_POR_FILA * 1000

        indice, t = HNSWIndex(8, 50, metric="cosine", seed=42), time.perf_counter()
        for i in range(len(base)):
            indice.insert(i, base[i])
        construccion = time.perf_counter() - t
        print(f"\n{n} vectores: construcción {construccion:.0f} s; exacta numpy {ms_numpy:.1f} ms, "
              f"fila por fila {ms_fila:.0f} ms", flush=True)
        for k, ef in BUSQUEDAS:
            recall, visitados, t = [], [], time.perf_counter()
            for q in consultas:
                r = indice.search(base[q], k=k + 1, ef_search=max(ef, k + 1))
                ids = [i for i, _ in r.matches if i != q][:k]
                recall.append(len(set(ids) & set(exacta[q][:k])) / k)
                visitados.append(r.nodes_visited)
            ms = (time.perf_counter() - t) / CONSULTAS * 1000
            fila = dict(n=n, k=k, ef_search=ef, construccion_s=round(construccion), recall=round(float(np.mean(recall)), 4),
                        ms_hnsw=round(ms, 2), ms_exacta_numpy=round(ms_numpy, 2), ms_exacta_fila_por_fila=round(ms_fila),
                        visitados=round(float(np.mean(visitados))), visitados_pct=round(float(np.mean(visitados)) / n, 4))
            filas.append(fila)
            print(f"  k={k:3d} ef_search={ef:3d}: recall {fila['recall']:.3f}, {ms:.1f} ms, "
                  f"{fila['visitados']} nodos ({fila['visitados_pct']:.1%})", flush=True)
        json.dump({"ruido": RUIDO, "consultas": CONSULTAS, "filas": filas}, open(SALIDA, "w"), indent=1)
    print(f"\n{SALIDA}")


if __name__ == "__main__":
    main()
