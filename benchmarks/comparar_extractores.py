"""Compara P@10 por categoría COCO con SIFT y MobileNet, excluyendo la consulta."""
import argparse
import json
import os
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

from benchmarks.multimedia_category_precision import category_precision
from engine.features.registry import extract_features
from engine.indexes.hnsw import HNSWIndex


def comparar(dataset, salida):
    import cv2
    cv2.setNumThreads(1)
    subset = dataset / "coco1k"
    manifest = json.loads((subset / "instances_subset.json").read_text("utf-8"))
    archivos = sorted(image["file_name"] for image in manifest["images"])
    consultas = json.loads((subset / "queries.json").read_text("utf-8"))["queries"]
    ids = {nombre: i for i, nombre in enumerate(archivos)}
    resultados = []
    for nombre in ("sift", "mobilenet"):
        indice = HNSWIndex(metric="cosine")
        for i, archivo in enumerate(archivos):
            vector = extract_features("image", str(subset / "images" / archivo), nombre)
            if vector.any():
                indice.insert(i, vector)
            if (i + 1) % 100 == 0:
                print(f"{nombre}: {i+1}/{len(archivos)}", flush=True)
        for consulta in consultas:
            identificador = ids[consulta["query_file"]]
            vecinos = []
            if identificador in indice.vectors:
                vecinos = [archivos[i] for i, _ in indice.search(
                    indice.vectors[identificador], k=11).matches if i != identificador][:10]
            resultados.append({"size": 1000, "metric": "cosine", "technique": nombre,
                               "query_file": consulta["query_file"],
                               "category": consulta["category_name"], "found_files": vecinos})
    salida.mkdir(parents=True, exist_ok=True)
    (salida / "queries.json").write_text(json.dumps(resultados, indent=2), encoding="utf-8")
    precision = category_precision(dataset, resultados)
    (salida / "precision.json").write_text(json.dumps(precision, indent=2), encoding="utf-8")
    print(precision)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--salida", type=Path, default=Path("benchmarks/results/extractores"))
    args = parser.parse_args()
    comparar(args.dataset, args.salida)
