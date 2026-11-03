"""Índice HNSW para vectores densos."""

import random
from collections.abc import Sequence

import numpy as np


class HNSWIndex:
    """Grafo de vecinos por capas para búsqueda aproximada."""

    def __init__(self, M: int = 8, ef_construction: int = 50, *, seed: int = 0):
        if type(M) is not int or M < 2:
            raise ValueError("M debe ser un entero mayor o igual a 2")
        if type(ef_construction) is not int or ef_construction < M:
            raise ValueError("ef_construction debe ser un entero mayor o igual a M")
        self.M = M
        self.ef_construction = ef_construction
        self.seed = seed
        self._rng = random.Random(seed)
        self.dimension: int | None = None
        self.vectors: dict[int, np.ndarray] = {}
        self.levels: dict[int, int] = {}
        self.links: dict[int, list[set[int]]] = {}
        self.entrypoint: int | None = None
        self.max_level = -1

    def _random_level(self) -> int:
        level = 0
        while self._rng.random() < 1 / self.M:
            level += 1
        return level
