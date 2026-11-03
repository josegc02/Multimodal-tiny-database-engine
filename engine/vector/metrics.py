"""Métricas de similitud y distancia para vectores numéricos."""

import math
from collections.abc import Sequence


def euclidean(a: Sequence[float], b: Sequence[float]) -> float:
    """Distancia euclidiana entre dos vectores de igual dimensión."""
    return math.dist(a, b)
