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

class TestScalableKMeans:
    def test_blocks_give_the_same_labels_as_the_exact_assignment(self):
        rng = np.random.default_rng(0)
        X = rng.normal(size=(1000, 16))
        km = KMeans(k=12, random_state=1, batch_size=37).fit(X)
        exact = np.argmin(np.linalg.norm(X[:, None] - km.centroids[None], axis=2), axis=1)
        np.testing.assert_array_equal(km.predict(X), exact)

    def test_centroids_are_the_mean_of_their_cluster(self):
        X = np.random.default_rng(3).normal(size=(500, 4))
        km = KMeans(k=5, random_state=0, max_iter=300, tol=0).fit(X)
        labels = km.predict(X)
        for i in range(5):
            np.testing.assert_allclose(km.centroids[i], X[labels == i].mean(axis=0), atol=1e-9)

    def test_same_seed_same_vocabulary(self):
        X = np.random.default_rng(4).normal(size=(300, 8))
        np.testing.assert_array_equal(KMeans(k=6, random_state=9).fit(X).centroids,
                                      KMeans(k=6, random_state=9).fit(X).centroids)

    def test_trains_many_sift_like_descriptors(self):
        X = np.random.default_rng(5).random((20_000, 128)).astype(np.float32)
        km = KMeans(k=64, max_iter=3, random_state=0).fit(X)
        assert km.centroids.shape == (64, 128)

    def test_invalid_input(self):
        with pytest.raises(ValueError):
            KMeans(k=5).fit(np.zeros((3, 2)))
        with pytest.raises(ValueError):
            KMeans(k=0)
        with pytest.raises(ValueError):
            KMeans(k=2).predict(np.zeros((1, 2)))
