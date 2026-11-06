"""Carga reproducible de vectores SIFT de los subconjuntos COCO."""

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np


def load_subset(directory: Path, expected_size: int):
    manifest = json.loads((directory / "instances_subset.json").read_text(encoding="utf-8"))
    images = sorted(manifest["images"], key=lambda image: image["id"])
    if len(images) != expected_size:
        raise ValueError(f"{directory}: se esperaban {expected_size} imágenes, hay {len(images)}")
    filenames = [image["file_name"] for image in images]
    missing = [name for name in filenames if not (directory / "images" / name).is_file()]
    if missing:
        raise FileNotFoundError(f"Faltan {len(missing)} imágenes; primera: {missing[0]}")
    queries = json.loads((directory / "queries.json").read_text(encoding="utf-8"))["queries"]
    if not queries:
        raise ValueError("No hay consultas en queries.json")
    names = set(filenames)
    for query in queries:
        if query["query_file"] not in names:
            raise ValueError(f"Consulta fuera del corpus: {query['query_file']}")
    return filenames, queries


def extract_vectors(directory: Path, filenames: list[str], cache: Path) -> np.ndarray:
    """Se extrae una vez; el mismo arreglo alimenta todas las configuraciones."""
    if cache.is_file():
        with np.load(cache, allow_pickle=False) as saved:
            vectors = saved["vectors"]
            cached_names = saved["filenames"].tolist()
        if cached_names != filenames:
            raise ValueError("La caché no corresponde al manifiesto")
        if vectors.ndim != 2 or vectors.shape[0] != len(filenames) or not np.isfinite(vectors).all():
            raise ValueError("Caché de vectores inválida")
        return vectors
    from engine.features.image.sift import SIFTExtractor

    import cv2

    # Cada tarea procesa una imagen; OpenCV libera el GIL durante el trabajo
    # pesado. Se limita su paralelismo interno para no multiplicar los hilos.
    cv2.setNumThreads(1)
    workers = min(8, os.cpu_count() or 1)
    local = threading.local()

    def extract(filename):
        if not hasattr(local, "extractor"):
            local.extractor = SIFTExtractor(n_features=500)
        vector = local.extractor.extract_to_fixed_vector(directory / "images" / filename)
        if not np.isfinite(vector).all() or np.linalg.norm(vector) == 0:
            raise ValueError(f"Vector inválido: {filename}")
        return vector

    with ThreadPoolExecutor(max_workers=workers) as pool:
        vectors = list(pool.map(extract, filenames))
    result = np.asarray(vectors, dtype=np.float32)
    cache.parent.mkdir(parents=True, exist_ok=True)
    np.savez(cache, vectors=result, filenames=np.asarray(filenames))
    return result
