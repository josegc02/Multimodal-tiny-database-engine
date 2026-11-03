"""Índice IVF para vectores densos."""

from collections.abc import Mapping, Sequence

import numpy as np


class IVFIndex:
    """Agrupa vectores por su centroide más cercano."""

    def __init__(self, nlist: int, *, seed: int = 0):
        if not isinstance(nlist, int) or nlist < 1:
            raise ValueError("nlist debe ser un entero positivo")
        self.nlist = nlist
        self.seed = seed
        self.dimension: int | None = None
        self.centroids: np.ndarray | None = None
        self.lists: list[dict[int, np.ndarray]] = []

    def train(self, vectors: Mapping[int, Sequence[float]]) -> None:
        """Entrena K-Means y asigna todos los vectores a listas invertidas."""
        ids = list(vectors)
        data = np.asarray(list(vectors.values()), dtype=float)
        if data.ndim != 2 or data.shape[0] < self.nlist or data.shape[1] == 0:
            raise ValueError("Se requieren al menos nlist vectores de igual dimensión")
        if not np.isfinite(data).all():
            raise ValueError("Los vectores deben contener números finitos")

        rng = np.random.default_rng(self.seed)
        centroids = data[rng.choice(len(data), self.nlist, replace=False)].copy()
        for _ in range(100):
            assignments = np.argmin(
                np.sum((data[:, None, :] - centroids[None, :, :]) ** 2, axis=2),
                axis=1,
            )
            updated = centroids.copy()
            for i in range(self.nlist):
                members = data[assignments == i]
                if len(members):
                    updated[i] = members.mean(axis=0)
            if np.array_equal(updated, centroids):
                break
            centroids = updated

        assignments = np.argmin(
            np.sum((data[:, None, :] - centroids[None, :, :]) ** 2, axis=2),
            axis=1,
        )
        lists = [dict() for _ in range(self.nlist)]
        for identifier, vector, list_id in zip(ids, data, assignments):
            lists[int(list_id)][identifier] = vector.copy()
        self.dimension = data.shape[1]
        self.centroids = centroids
        self.lists = lists

    def search(self, query: Sequence[float], k: int = 10, nprobe: int = 1) -> list[tuple[int, float]]:
        """Busca los k vecinos más cercanos visitando nprobe listas."""
        if self.centroids is None:
            raise ValueError("El índice debe entrenarse antes de buscar")
        if not isinstance(k, int) or k < 1:
            raise ValueError("k debe ser un entero positivo")
        if not isinstance(nprobe, int) or not 1 <= nprobe <= self.nlist:
            raise ValueError("nprobe debe estar entre 1 y nlist")
        query = np.asarray(query, dtype=float)
        if query.shape != (self.dimension,) or not np.isfinite(query).all():
            raise ValueError("La consulta debe tener la dimensión del índice y valores finitos")

        distances = np.linalg.norm(self.centroids - query, axis=1)
        nearest_lists = np.argsort(distances, kind="stable")[:nprobe]
        candidates = (
            (identifier, float(np.linalg.norm(vector - query)))
            for list_id in nearest_lists
            for identifier, vector in self.lists[int(list_id)].items()
        )
        return sorted(candidates, key=lambda item: (item[1], item[0]))[:k]
