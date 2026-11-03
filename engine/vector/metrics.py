"""Métricas de similitud y distancia para vectores numéricos."""

import math
from collections.abc import Sequence


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
