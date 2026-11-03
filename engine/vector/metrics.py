"""Métricas de similitud y distancia para vectores numéricos."""

import math
from collections.abc import Sequence

import numpy as np


def euclidean(a: Sequence[float], b: Sequence[float]) -> float:
    """Distancia euclidiana entre dos vectores de igual dimensión."""
    return math.dist(a, b)


def dot_product(a: Sequence[float], b: Sequence[float]) -> float:
    """Producto punto entre dos vectores de igual dimensión."""
    if len(a) != len(b):
        raise ValueError("Los vectores deben tener la misma dimensión")
    return math.fsum(x * y for x, y in zip(a, b))


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Similitud del coseno; no está definida para vectores de norma cero."""
    if len(a) != len(b):
        raise ValueError("Los vectores deben tener la misma dimensión")
    norm_a = math.dist(a, [0] * len(a))
    norm_b = math.dist(b, [0] * len(b))
    if norm_a == 0 or norm_b == 0:
        raise ValueError("La similitud del coseno requiere vectores no nulos")
    return dot_product(a, b) / (norm_a * norm_b)


def _batch_arrays(a, b) -> tuple[np.ndarray, np.ndarray]:
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if a.ndim != 2 or b.ndim != 2 or a.shape != b.shape:
        raise ValueError("Los lotes deben tener la misma forma (n, d)")
    return a, b


def euclidean_batch(a, b) -> np.ndarray:
    """Distancia por fila entre dos lotes de forma (n, d)."""
    a, b = _batch_arrays(a, b)
    return np.linalg.norm(a - b, axis=1)


def dot_product_batch(a, b) -> np.ndarray:
    """Producto punto por fila entre dos lotes de forma (n, d)."""
    a, b = _batch_arrays(a, b)
    return np.einsum("ij,ij->i", a, b)


def cosine_similarity_batch(a, b) -> np.ndarray:
    """Similitud del coseno por fila; rechaza cualquier vector nulo."""
    a, b = _batch_arrays(a, b)
    norms = np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1)
    if np.any(norms == 0):
        raise ValueError("La similitud del coseno requiere vectores no nulos")
    return np.einsum("ij,ij->i", a, b) / norms
