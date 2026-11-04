"""Tests unitarios para el algoritmo K-Means."""
import numpy as np
import pytest
from pathlib import Path
import tempfile
from engine.features.image.kmeans import KMeans


class TestKMeans:
    def test_fit_simple_clusters(self):
        """Prueba que K-Means separa correctamente dos clusters obvios."""
        # Cluster 1 alrededor de (1,1), Cluster 2 alrededor de (10,10)
        X = np.array([
            [1.0, 1.0], [1.2, 1.1], [0.9, 1.2],
            [10.0, 10.0], [10.1, 9.9], [9.8, 10.2]
        ], dtype=float)
        
        km = KMeans(k=2, random_state=42)
        km.fit(X)
        
        assert km.centroids.shape == (2, 2)
        
        # Los centroides deben estar cerca de (1,1) y (10,10)
        distances = np.linalg.norm(km.centroids - np.array([[1,1], [10,10]]), axis=1)
        assert np.all(distances < 2.0)

    def test_predict_assignments(self):
        """Prueba que predict asigna los puntos al centroide correcto."""
        X = np.array([[0, 0], [1, 1], [10, 10], [11, 11]], dtype=float)
        km = KMeans(k=2, random_state=42)
        km.fit(X)
        
        labels = km.predict(X)
        # Los dos primeros deben tener la misma etiqueta, y los dos últimos otra
        assert labels[0] == labels[1]
        assert labels[2] == labels[3]
        assert labels[0] != labels[2]

    def test_save_and_load(self):
        """Prueba la persistencia del codebook."""
        X = np.random.rand(20, 5)
        km = KMeans(k=3, random_state=42)
        km.fit(X)
        
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "codebook.npy"
            km.save(str(path))
            
            km_loaded = KMeans.load(str(path), k=3)
            np.testing.assert_array_almost_equal(km.centroids, km_loaded.centroids)