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
