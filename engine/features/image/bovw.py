"""
Bag of Visual Words (BoVW) extractor.
Convierte imágenes en vectores de dimensión fija (K) usando un vocabulario visual
(codebook) y ponderación TF-IDF. Las fórmulas están en engine.features.bow, que
también sirve para Bag of Audio Words.
"""

from pathlib import Path
from typing import List, Optional, Union

import numpy as np

from engine.features.bow import BagOfWords, idf_from, tf_idf
from engine.features.image.sift import SIFTExtractor


class BoVWExtractor:
    """
    Extractor de características basado en Bag of Visual Words.
    """

    def __init__(self, k: int, codebook_path: Optional[Union[str, Path]] = None):
        """
        Args:
            k: Número de palabras visuales (centroides).
            codebook_path: Ruta al archivo .npy con los centroides o al .npz de BagOfWords.
        """
        self.k = k
        self.centroids = None
        self.idf = None
        self._sift = None

        if codebook_path:
            self.load_codebook(codebook_path)

    # --- Persistencia del Codebook ---

    def load_codebook(self, path: Union[str, Path]) -> None:
        """Carga los centroides (.npy) o el vocabulario completo con su IDF (.npz)."""
        if str(path).endswith(".npz"):
            bow = BagOfWords.load(path)
            self.centroids, self.idf = bow.centroids, bow.idf
        else:
            self.centroids = np.load(str(path))
        if self.centroids.shape[0] != self.k:
            raise ValueError(f"El codebook tiene {self.centroids.shape[0]} centroides, se esperaban {self.k}")

    def save_codebook(self, path: Union[str, Path]) -> None:
        """Guarda los centroides en un archivo .npy."""
        if self.centroids is None:
            raise ValueError("No hay codebook para guardar")
        np.save(str(path), self.centroids)

    # --- Extracción de SIFT crudo ---

    def _extract_sift_descriptors(self, image: Union[str, Path, np.ndarray]) -> np.ndarray:
        """Extrae los descriptores SIFT crudos (sin promediar) de una imagen: (N, 128)."""
        if self._sift is None:
            self._sift = SIFTExtractor()
        return self._sift.extract_descriptors(image)

    # --- Pipeline BoVW ---

    def _bow(self) -> BagOfWords:
        if self.centroids is None:
            raise ValueError("No hay codebook cargado")
        return BagOfWords(self.centroids, self.idf)

    def compute_histogram(self, descriptors: np.ndarray) -> np.ndarray:
        """
        Genera el histograma de palabras visuales para un conjunto de descriptores.
        """
        if descriptors is None or len(descriptors) == 0:
            return np.zeros(self.k, dtype=float)
        return self._bow().histogram(descriptors)

    def compute_idf(self, histograms: List[np.ndarray]) -> np.ndarray:
        """
        IDF = log10(N / df) a partir de los histogramas del corpus de entrenamiento.
        """
        self.idf = idf_from(histograms)
        return self.idf

    def apply_tfidf(self, histogram: np.ndarray) -> np.ndarray:
        """
        Aplica (1 + log10 tf) · idf y normaliza el vector resultante (L2).
        """
        if self.idf is None:
            raise ValueError("IDF no calculado. Ejecuta compute_idf primero.")
        return tf_idf(histogram, self.idf)

    def extract(self, image: Union[str, Path, np.ndarray]) -> np.ndarray:
        """
        Función principal ExtractFeatures. Convierte una imagen en su vector BoVW-TFIDF.
        """
        descriptors = self._extract_sift_descriptors(image)
        histogram = self.compute_histogram(descriptors)
        return self.apply_tfidf(histogram)
