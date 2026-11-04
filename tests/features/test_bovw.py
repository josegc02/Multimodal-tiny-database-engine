"""Tests unitarios para el extractor Bag of Visual Words."""
import numpy as np
import pytest
from engine.features.image.bovw import BoVWExtractor


class TestBoVWExtractor:
    def setup_method(self):
        """Configura un extractor dummy con 3 palabras visuales."""
        self.bovw = BoVWExtractor(k=3)
        # Centroides en 2D para facilitar el cálculo manual
        self.bovw.centroids = np.array([
            [0.0, 0.0],  # Palabra 0
            [10.0, 10.0], # Palabra 1
            [20.0, 20.0]  # Palabra 2
        ], dtype=float)

    def test_compute_histogram(self):
        """Prueba la generación del histograma."""
        # 2 descriptores cerca de la palabra 0, 1 cerca de la palabra 1
        descriptors = np.array([
            [0.1, 0.1], [0.2, 0.2], [10.1, 9.9]
        ], dtype=float)
        
        hist = self.bovw.compute_histogram(descriptors)
        np.testing.assert_array_equal(hist, [2.0, 1.0, 0.0])

    def test_compute_idf(self):
        """Prueba el cálculo de IDF."""
        # 3 documentos (imágenes)
        histograms = [
            np.array([5, 0, 0]), # Solo palabra 0
            np.array([0, 3, 0]), # Solo palabra 1
            np.array([2, 2, 0])  # Palabras 0 y 1
        ]
        
        idf = self.bovw.compute_idf(histograms)
        
        # Palabra 0 aparece en 2 docs, Palabra 1 en 2 docs, Palabra 2 en 0 docs
        # IDF = log((N+1)/df) = log(4/df)
        assert idf[0] == pytest.approx(np.log(4/2))
        assert idf[2] == pytest.approx(np.log(4/1)) # df se ajusta a 1 mínimo

    def test_apply_tfidf_normalization(self):
        """Prueba que TF-IDF normaliza el vector a norma 1."""
        self.bovw.compute_idf([np.array([1, 1, 1]), np.array([1, 0, 0])])
        
        histogram = np.array([2.0, 1.0, 0.0])
        tfidf_vector = self.bovw.apply_tfidf(histogram)
        
        # La norma L2 debe ser 1 (o muy cercana)
        assert np.linalg.norm(tfidf_vector) == pytest.approx(1.0)