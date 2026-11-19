"""HNSW frente a búsqueda exacta sobre las imágenes de la tienda.

Uso, desde la raíz (después de ``python -m benchmarks.tienda.medir``, que deja los
vectores en datasets/tienda/benchmark)::

    python -m benchmarks.tienda.hnsw

Para MobileNet (1280 dimensiones) y SIFT + BoVW (1024) sobre los 7,995 productos:
construcción, recall@k contra la búsqueda exacta por coseno, latencia, nodos
visitados y el efecto en la recomendación (P@10 de mismo tipo con solo la imagen).
El índice es el del motor (engine/indexes/hnsw.py). La app usa M=8,
ef_construction=50; en recomendaciones busca k=102 con ef_search=102.
"""
import csv
import json
import random
import time
from pathlib import Path

import numpy as np

from benchmarks.tienda.medir import CACHE, PRODUCTOS, tipo_titulo
from engine.indexes.hnsw import HNSWIndex

SALIDA = Path(__file__).with_name("hnsw.json")
CONSULTAS = 500
CONFIGURACIONES = [(8, 50), (16, 100)]  # (M, ef_construction); la primera es la de la app
BUSQUEDAS = [(10, 10), (10, 50), (10, 100), (10, 200), (102, 102), (102, 200), (102, 400)]  # (k, ef_search)


def main():
    productos = list(csv.DictReader(open(PRODUCTOS, encoding="utf-8")))
    tipo = [tipo_titulo(p) for p in productos]
    salida = {"consultas": CONSULTAS, "productos": len(productos), "filas": []}
    for nombre in ("mobilenet", "sift_bovw"):
        v = np.load(CACHE / f"{nombre}.npy").astype(np.float64)
        normas = np.linalg.norm(v, axis=1)
        validos = [i for i in range(len(v)) if normas[i] > 0]
        v[validos] /= normas[validos, None]
        consultas = random.Random(5).sample(validos, CONSULTAS)
        etiquetadas = [q for q in consultas if tipo[q]]

        # Exacta vectorizada: producto punto con todos en numpy y selección de los mejores.
        base = v[validos]
        exacta, t = {}, time.perf_counter()
        for q in consultas:
            sim = base @ v[q]
            top = np.argpartition(-sim, 103)[:103]
            exacta[q] = [validos[i] for i in top[np.argsort(-sim[top])] if validos[i] != q][:101]
        ms_exacta = (time.perf_counter() - t) / len(consultas) * 1000
        # Exacta fila por fila, como un recorrido secuencial del motor (50 consultas).
        t = time.perf_counter()
        for q in consultas[:50]:
            puntos = [float(np.dot(v[i], v[q])) for i in validos]
            sorted(range(len(validos)), key=lambda i: -puntos[i])[:102]
        ms_secuencial = (time.perf_counter() - t) / 50 * 1000
        p_exacta = np.mean([np.mean([tipo[x] == tipo[q] for x in exacta[q][:10]]) for q in etiquetadas])
        print(f"\n{nombre}: {len(validos)} vectores de {v.shape[1]} dim.; exacta numpy {ms_exacta:.2f} ms, "
              f"fila por fila {ms_secuencial:.1f} ms; "
              f"P@10 de tipo {p_exacta:.3f}", flush=True)

        for M, efc in CONFIGURACIONES:
            indice, t = HNSWIndex(M, efc, metric="cosine", seed=42), time.perf_counter()
            for i in validos:
                indice.insert(i, v[i])
            construccion = time.perf_counter() - t
            print(f"  M={M}, ef_construction={efc}: construcción {construccion:.0f} s", flush=True)
            for k, ef in BUSQUEDAS:
                recall, visitados, encontrados, t = [], [], {}, time.perf_counter()
                for q in consultas:
                    r = indice.search(v[q], k=k + 1, ef_search=max(ef, k + 1))
                    ids = [i for i, _ in r.matches if i != q][:k]
                    encontrados[q] = ids
                    visitados.append(r.nodes_visited)
                    recall.append(len(set(ids) & set(exacta[q][:k])) / k)
                ms = (time.perf_counter() - t) / len(consultas) * 1000
                p10 = np.mean([np.mean([tipo[x] == tipo[q] for x in encontrados[q][:10]]) for q in etiquetadas])
                fila = dict(vector=nombre, dim=int(v.shape[1]), M=M, ef_construction=efc, construccion_s=round(construccion, 1),
                            k=k, ef_search=ef, recall=round(float(np.mean(recall)), 4),
                            ms_hnsw=round(ms, 2), ms_exacta_numpy=round(ms_exacta, 2),
                            ms_exacta_fila_por_fila=round(ms_secuencial, 1),
                            visitados=round(float(np.mean(visitados))), p10_tipo_hnsw=round(float(p10), 4),
                            p10_tipo_exacta=round(float(p_exacta), 4))
                salida["filas"].append(fila)
                print(f"    k={k:3d} ef_search={ef:3d}: recall {fila['recall']:.3f}, {ms:6.2f} ms, "
                      f"{fila['visitados']:5d} nodos visitados ({fila['visitados'] / len(validos):.0%}), "
                      f"P@10 tipo {p10:.3f}", flush=True)
    json.dump(salida, open(SALIDA, "w", encoding="utf-8"), indent=1)
    print(f"\n{SALIDA}")


if __name__ == "__main__":
    main()
