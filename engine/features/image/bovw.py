"""
Bag of Visual Words (BoVW) extractor.
Convierte imágenes en vectores de dimensión fija (K) usando un vocabulario visual
(codebook) y ponderación TF-IDF.
"""

import cv2
import numpy as np
from pathlib import Path
from typing import Union, Optional, List


class BoVWExtractor:
    """
    Extractor de características basado en Bag of Visual Words.
    """

    def __init__(self, k: int, codebook_path: Optional[Union[str, Path]] = None):
        """
        Args:
            k: Número de palabras visuales (centroides).
            codebook_path: Ruta al archivo .npy con los centroides entrenados.
        """
        self.k = k
        self.centroids = None
        self.idf = None
        
        if codebook_path:
            self.load_codebook(codebook_path)

    # --- Persistencia del Codebook ---

    def load_codebook(self, path: Union[str, Path]) -> None:
        """Carga los centroides (vocabulario visual) desde un archivo .npy."""
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
        """Extrae los descriptores SIFT crudos (sin promediar) de una imagen."""
        if isinstance(image, (str, Path)):
            img = cv2.imread(str(image), cv2.IMREAD_GRAYSCALE)
        else:
            img = image
            if len(img.shape) == 3:
                img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        if img is None:
            raise ValueError("No se pudo cargar la imagen")

        sift = cv2.SIFT_create()
        _, descriptors = sift.detectAndCompute(img, None)
        return descriptors  # Retorna array de forma (N, 128)

    # --- Pipeline BoVW ---

    def compute_histogram(self, descriptors: np.ndarray) -> np.ndarray:
        """
        Genera el histograma de palabras visuales para un conjunto de descriptores.
        """
        if descriptors is None or len(descriptors) == 0:
            return np.zeros(self.k, dtype=float)
        
        # Calcular distancia euclidiana entre cada descriptor y cada centroide
        # descriptors: (N, 128), centroids: (K, 128) -> distances: (N, K)
        distances = np.linalg.norm(descriptors[:, np.newaxis] - self.centroids, axis=2)
        labels = np.argmin(distances, axis=1)
        
        # Contar frecuencias
        histogram, _ = np.histogram(labels, bins=np.arange(self.k + 1))
        return histogram.astype(float)

    def compute_idf(self, histograms: List[np.ndarray]) -> np.ndarray:
        """
        Calcula el Inverse Document Frequency (IDF) a partir de una lista de histogramas
        (uno por imagen en el corpus de entrenamiento).
        """
        N = len(histograms)
        if N == 0:
            raise ValueError("Se necesita al menos un histograma para calcular IDF")
        
        # df: document frequency (número de documentos donde la palabra aparece al menos una vez)
        df = np.sum(np.array(histograms) > 0, axis=0)
        df = np.maximum(df, 1)  # Evitar división por cero
        
        # Fórmula IDF suavizada
        self.idf = np.log((N + 1) / df)
        return self.idf

    def apply_tfidf(self, histogram: np.ndarray) -> np.ndarray:
        """
        Aplica la ponderación TF-IDF y normaliza el vector resultante (L2).
        """
        if self.idf is None:
            raise ValueError("IDF no calculado. Ejecuta compute_idf primero.")
        
        total = np.sum(histogram)
        if total == 0:
            return np.zeros(self.k, dtype=float)
        
        # Term Frequency
        tf = histogram / total
        
        # TF-IDF
        tfidf = tf * self.idf
        
        # Normalización L2
        norm = np.linalg.norm(tfidf)
        if norm > 0:
            tfidf = tfidf / norm
            
        return tfidf

    def extract(self, image: Union[str, Path, np.ndarray]) -> np.ndarray:
        """
        Función principal ExtractFeatures. Convierte una imagen en su vector BoVW-TFIDF.
        """
        descriptors = self._extract_sift_descriptors(image)
        histogram = self.compute_histogram(descriptors)
        return self.apply_tfidf(histogram)