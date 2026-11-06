"""Índice IVF para vectores densos."""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class SearchResult:
    matches: list[tuple[int, float]]
    vectors_compared: int


class IVFIndex:
    """Agrupa vectores por su centroide más cercano."""

    def __init__(self, nlist: int, *, metric: str = "euclidean", seed: int = 0):
        if not isinstance(nlist, int) or nlist < 1:
            raise ValueError("nlist debe ser un entero positivo")
        if metric not in ("euclidean", "dot_product", "cosine"):
            raise ValueError("Métrica no soportada")
        self.nlist = nlist
        self.metric = metric
        self.seed = seed
        self.dimension: int | None = None
        self.centroids: np.ndarray | None = None
        self.lists: list[dict[int, np.ndarray]] = []

    def train(self, vectors: Mapping[int, Sequence[float]]) -> None:
        """Entrena K-Means y asigna todos los vectores a listas invertidas."""
        ids = list(vectors)
        if any(type(identifier) is not int for identifier in ids):
            raise ValueError("Los identificadores deben ser enteros")
        data = np.asarray(list(vectors.values()), dtype=float)
        if data.ndim != 2 or data.shape[0] < self.nlist or data.shape[1] == 0:
            raise ValueError("Se requieren al menos nlist vectores de igual dimensión")
        if not np.isfinite(data).all():
            raise ValueError("Los vectores deben contener números finitos")
        if self.metric == "cosine" and np.any(np.linalg.norm(data, axis=1) == 0):
            raise ValueError("El coseno requiere vectores no nulos")

        rng = np.random.default_rng(self.seed)
        training_data = data
        if self.metric == "cosine":
            training_data = data / np.linalg.norm(data, axis=1)[:, None]
        centroids = training_data[rng.choice(len(data), self.nlist, replace=False)].copy()
        for _ in range(100):
            training_metric = "cosine" if self.metric == "cosine" else "euclidean"
            assignments = self._assign(training_data, centroids, training_metric)
            updated = centroids.copy()
            for i in range(self.nlist):
                members = training_data[assignments == i]
                if len(members):
                    updated[i] = members.mean(axis=0)
                    if self.metric == "cosine":
                        norm = np.linalg.norm(updated[i])
                        if norm:
                            updated[i] /= norm
                        else:
                            updated[i] = centroids[i]
            if np.array_equal(updated, centroids):
                break
            centroids = updated

        assignments = self._assign(training_data, centroids, self.metric)
        lists = [dict() for _ in range(self.nlist)]
        for identifier, vector, list_id in zip(ids, data, assignments):
            lists[int(list_id)][identifier] = vector.copy()
        self.dimension = data.shape[1]
        self.centroids = centroids
        self.lists = lists

    @staticmethod
    def _assign(data: np.ndarray, centroids: np.ndarray, metric: str) -> np.ndarray:
        # Evitar el arreglo (vectores, centroides, dimensiones): con 100K x 316
        # x 128 en float64 supera 30 GiB. Cada bloque solo crea una matriz
        # (hasta 2048, centroides), tanto para euclidiana como para coseno.
        assignments = np.empty(len(data), dtype=np.intp)
        center_transpose = centroids.T
        center_norms = np.einsum("ij,ij->i", centroids, centroids) if metric == "euclidean" else None
        for start in range(0, len(data), 2048):
            stop = min(start + 2048, len(data))
            scores = data[start:stop] @ center_transpose
            if metric == "euclidean":
                # ||x-c||² = ||x||² + ||c||² - 2 x·c;
                # ||x||² es igual para todos los centroides de una fila.
                scores *= -2
                scores += center_norms
                assignments[start:stop] = np.argmin(scores, axis=1)
            else:
                assignments[start:stop] = np.argmax(scores, axis=1)
        return assignments

    def insert(self, identifier: int, vector: Sequence[float]) -> None:
        """Inserta un vector en la lista de su centroide más cercano."""
        if self.centroids is None:
            raise ValueError("El índice debe entrenarse antes de insertar")
        if type(identifier) is not int:
            raise ValueError("El identificador debe ser un entero")
        if any(identifier in items for items in self.lists):
            raise ValueError("El identificador ya existe")
        vector = self._validate_vector(vector)
        list_id = int(self._assign(vector[None, :], self.centroids, self.metric)[0])
        self.lists[list_id][identifier] = vector.copy()

    def delete(self, identifier: int) -> bool:
        """Elimina un vector; devuelve False si no existe."""
        for items in self.lists:
            if identifier in items:
                del items[identifier]
                return True
        return False

    def save(self, path: str | Path) -> None:
        """Guarda centroides y listas en un archivo JSON."""
        if self.centroids is None:
            raise ValueError("El índice debe entrenarse antes de guardarlo")
        payload = {
            "version": 1,
            "nlist": self.nlist,
            "metric": self.metric,
            "seed": self.seed,
            "dimension": self.dimension,
            "centroids": self.centroids.tolist(),
            "lists": [
                [[identifier, vector.tolist()] for identifier, vector in items.items()]
                for items in self.lists
            ],
        }
        Path(path).write_text(json.dumps(payload), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "IVFIndex":
        """Carga un índice guardado con save."""
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if payload["version"] != 1:
            raise ValueError("Versión de índice no soportada")
        index = cls(payload["nlist"], metric=payload["metric"], seed=payload["seed"])
        index.dimension = payload["dimension"]
        index.centroids = np.asarray(payload["centroids"], dtype=float)
        if index.centroids.shape != (index.nlist, index.dimension) or not np.isfinite(index.centroids).all():
            raise ValueError("Centroides inválidos")
        if len(payload["lists"]) != index.nlist:
            raise ValueError("Número de listas inválido")
        index.lists = [
            {identifier: index._validate_vector(vector) for identifier, vector in items}
            for items in payload["lists"]
        ]
        return index

    def _validate_vector(self, vector: Sequence[float]) -> np.ndarray:
        result = np.asarray(vector, dtype=float)
        if result.shape != (self.dimension,) or not np.isfinite(result).all():
            raise ValueError("El vector debe tener la dimensión del índice y valores finitos")
        if self.metric == "cosine" and np.linalg.norm(result) == 0:
            raise ValueError("El coseno requiere vectores no nulos")
        return result

    def search(self, query: Sequence[float], k: int = 10, nprobe: int = 1) -> SearchResult:
        """Busca vecinos y devuelve también cuántos vectores se compararon."""
        if self.centroids is None:
            raise ValueError("El índice debe entrenarse antes de buscar")
        if not isinstance(k, int) or k < 1:
            raise ValueError("k debe ser un entero positivo")
        if not isinstance(nprobe, int) or not 1 <= nprobe <= self.nlist:
            raise ValueError("nprobe debe estar entre 1 y nlist")
        query = self._validate_vector(query)

        if self.metric == "euclidean":
            centroid_scores = np.linalg.norm(self.centroids - query, axis=1)
        else:
            centroid_scores = self.centroids @ query
        descending = self.metric != "euclidean"
        nearest_lists = sorted(
            range(self.nlist),
            key=lambda i: (-centroid_scores[i] if descending else centroid_scores[i], i),
        )[:nprobe]
        vectors_compared = sum(len(self.lists[i]) for i in nearest_lists)
        candidates = (
            (identifier, self._score(vector, query))
            for list_id in nearest_lists
            for identifier, vector in self.lists[list_id].items()
        )
        matches = sorted(
            candidates, key=lambda item: (-item[1] if descending else item[1], item[0])
        )[:k]
        return SearchResult(matches, vectors_compared)

    def _score(self, vector: np.ndarray, query: np.ndarray) -> float:
        if self.metric == "euclidean":
            return float(np.linalg.norm(vector - query))
        product = float(vector @ query)
        if self.metric == "dot_product":
            return product
        return product / float(np.linalg.norm(vector) * np.linalg.norm(query))
