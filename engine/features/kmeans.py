"""K-Means para construir vocabularios de Bag of Visual/Audio Words.

Una imagen aporta cientos de descriptores SIFT, así que el vocabulario se
entrena con cientos de miles de vectores. Calcular todas las distancias de una
vez ocuparía N × K × D números; aquí se asigna por bloques de `batch_size`
filas con ||x - c||² = ||x||² - 2 x·c + ||c||², de modo que la memoria es
O(batch_size × K). Los centroides iniciales se eligen con k-means++.
"""

from __future__ import annotations

import numpy as np


class KMeans:
    """Algoritmo de clustering K-Means (Lloyd) con inicialización k-means++."""

    def __init__(self, k: int = 100, max_iter: int = 100, tol: float = 1e-4,
                 random_state: int | None = None, batch_size: int = 4096):
        if type(k) is not int or k < 1:
            raise ValueError("k debe ser un entero positivo")
        self.k = k
        self.max_iter = max_iter
        self.tol = tol
        self.random_state = random_state
        self.batch_size = batch_size
        self.centroids: np.ndarray | None = None
        self.iterations = 0

    def _nearest(self, X: np.ndarray, centroids: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """(etiqueta, distancia²) del centroide más cercano a cada fila, por bloques."""
        labels = np.empty(len(X), dtype=np.int64)
        distances = np.empty(len(X), dtype=np.float64)
        squared = np.einsum("ij,ij->i", centroids, centroids)
        for start in range(0, len(X), self.batch_size):
            block = X[start:start + self.batch_size]
            scores = squared[None, :] - 2.0 * block @ centroids.T
            best = np.argmin(scores, axis=1)
            labels[start:start + len(block)] = best
            nearest = scores[np.arange(len(block)), best] + np.einsum("ij,ij->i", block, block)
            distances[start:start + len(block)] = np.maximum(nearest, 0.0)
        return labels, distances

    def _initial_centroids(self, X: np.ndarray, rng: np.random.Generator) -> np.ndarray:
        """k-means++: cada centroide nuevo se elige con probabilidad ∝ distancia² al más cercano."""
        centroids = np.empty((self.k, X.shape[1]), dtype=np.float64)
        centroids[0] = X[rng.integers(len(X))]
        closest = np.sum((X - centroids[0]) ** 2, axis=1)
        for i in range(1, self.k):
            total = closest.sum()
            index = rng.choice(len(X), p=closest / total) if total > 0 else rng.integers(len(X))
            centroids[i] = X[index]
            closest = np.minimum(closest, np.sum((X - centroids[i]) ** 2, axis=1))
        return centroids

    def fit(self, X: np.ndarray) -> "KMeans":
        X = np.asarray(X, dtype=np.float64)
        if X.ndim != 2 or len(X) < self.k:
            raise ValueError(f"Se requieren al menos k={self.k} vectores de igual dimensión")
        if not np.isfinite(X).all():
            raise ValueError("Los vectores deben contener números finitos")
        rng = np.random.default_rng(self.random_state)
        centroids = self._initial_centroids(X, rng)
        for iteration in range(1, self.max_iter + 1):
            labels, _ = self._nearest(X, centroids)
            counts = np.bincount(labels, minlength=self.k)
            sums = np.stack([np.bincount(labels, weights=X[:, j], minlength=self.k)
                             for j in range(X.shape[1])], axis=1)
            updated = centroids.copy()
            filled = counts > 0
            # Un cluster vacío conserva su centroide.
            updated[filled] = sums[filled] / counts[filled, None]
            shift = np.linalg.norm(updated - centroids)
            centroids = updated
            self.iterations = iteration
            if shift < self.tol:
                break
        self.centroids = centroids
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        if self.centroids is None:
            raise ValueError("El modelo debe entrenarse antes de predecir")
        X = np.asarray(X, dtype=np.float64)
        if len(X) == 0:
            return np.empty(0, dtype=np.int64)
        return self._nearest(X, self.centroids)[0]

    def save(self, path: str) -> None:
        np.save(path, self.centroids)

    @classmethod
    def load(cls, path: str, k: int) -> "KMeans":
        """Carga un modelo K-Means desde un archivo .npy."""
        model = cls(k=k)
        model.centroids = np.load(path)
        if model.centroids.shape[0] != k:
            raise ValueError(f"El archivo tiene {model.centroids.shape[0]} centroides, se esperaban {k}")
        return model
