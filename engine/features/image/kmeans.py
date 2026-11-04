import numpy as np


class KMeans:
    """Algoritmo de clustering K-Means."""

    def __init__(self, k: int = 100, max_iter: int = 100, tol: float = 1e-4, random_state: int = None):
        self.k = k
        self.max_iter = max_iter
        self.tol = tol
        self.random_state = random_state
        self.centroids = None

    def fit(self, X: np.ndarray) -> None:

        if self.random_state is not None:
            np.random.seed(self.random_state)
        
        # 1. Inicialización: Elegir k puntos aleatorios del dataset como centroides
        indices = np.random.choice(X.shape[0], self.k, replace=False)
        self.centroids = X[indices].copy()

        for _ in range(self.max_iter):
            # 2. Asignación: Calcular distancia euclidiana de cada punto a cada centroide
            # X: (N, D), Centroids: (K, D) -> Distances: (N, K)
            distances = np.linalg.norm(X[:, np.newaxis] - self.centroids, axis=2)
            labels = np.argmin(distances, axis=1)

            # 3. Actualización: Recalcular centroides como la media de los puntos asignados
            new_centroids = np.array([
                X[labels == i].mean(axis=0) if np.any(labels == i) else self.centroids[i]
                for i in range(self.k)
            ])

            # 4. Verificar convergencia (si los centroides casi no se mueven)
            shift = np.linalg.norm(new_centroids - self.centroids)
            self.centroids = new_centroids
            
            if shift < self.tol:
                break

    def predict(self, X: np.ndarray) -> np.ndarray:

        distances = np.linalg.norm(X[:, np.newaxis] - self.centroids, axis=2)
        return np.argmin(distances, axis=1)

    def save(self, path: str) -> None:
        np.save(path, self.centroids)

    @classmethod
    def load(cls, path: str, k: int) -> "KMeans":
        """Carga un modelo K-Means desde un archivo .npy."""
        model = cls(k=k)
        model.centroids = np.load(path)
        return model