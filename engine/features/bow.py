"""Bag of Visual/Audio Words: descriptores locales -> vector TF-IDF de dimensión K.

Sigue el pipeline de la clase 11 (Modelos de Recuperación Multimedia 2):

1. Vocabulario: K-Means sobre descriptores locales muestreados de muchos
   archivos (SIFT por punto clave o MFCC por ventana); cada centroide es una
   palabra visual o auditiva.
2. Cuantización: cada descriptor se asigna a la palabra más cercana (1-NN) y se
   cuenta cuántos caen en cada una: el histograma del archivo.
3. TF-IDF: w = (1 + log10 tf) · log10(N / df), con N los archivos de
   entrenamiento y df en cuántos aparece la palabra, y normalización L2.

Para audio "solo cambia el extractor": la misma clase sirve para ambos tipos.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional, Sequence

import numpy as np

from engine.features.kmeans import KMeans

DEFAULT_K = 256
DEFAULT_SAMPLE = 100_000  # descriptores usados para entrenar K-Means
FORMAT_VERSION = 1


def idf_from(histograms: Sequence[np.ndarray]) -> np.ndarray:
    """log10(N / df) por palabra; una palabra que no aparece en ningún archivo pesa 0."""
    if not len(histograms):
        raise ValueError("Se necesita al menos un histograma para calcular el IDF")
    counts = np.asarray(histograms, dtype=np.float64)
    df = np.count_nonzero(counts > 0, axis=0)
    idf = np.zeros(counts.shape[1], dtype=np.float64)
    seen = df > 0
    idf[seen] = np.log10(len(counts) / df[seen])
    return idf


def tf_idf(histogram: np.ndarray, idf: np.ndarray) -> np.ndarray:
    """(1 + log10 tf) · idf con normalización L2; un histograma vacío queda en ceros."""
    histogram = np.asarray(histogram, dtype=np.float64)
    weights = np.zeros_like(histogram)
    present = histogram > 0
    weights[present] = (1.0 + np.log10(histogram[present])) * idf[present]
    norm = np.linalg.norm(weights)
    return weights / norm if norm > 0 else weights


def sample_descriptors(descriptor_sets: Sequence[np.ndarray], sample: int, seed: int) -> np.ndarray:
    """Hasta `sample` descriptores, tomados de cada archivo en proporción a los que tiene."""
    sets = [np.asarray(d, dtype=np.float32) for d in descriptor_sets if len(d)]
    if not sets:
        raise ValueError("Ningún archivo tiene descriptores locales")
    total = sum(len(d) for d in sets)
    if total <= sample:
        return np.concatenate(sets)
    rng = np.random.default_rng(seed)
    chosen = []
    for d in sets:
        take = max(1, round(sample * len(d) / total))
        chosen.append(d[rng.choice(len(d), min(take, len(d)), replace=False)])
    return np.concatenate(chosen)


class BagOfWords:
    """Vocabulario (centroides) + IDF; convierte descriptores locales en un vector de dimensión K."""

    def __init__(self, centroids: np.ndarray, idf: Optional[np.ndarray] = None, *,
                 kind: str = "", documents: int = 0):
        self.centroids = np.asarray(centroids, dtype=np.float64)
        if self.centroids.ndim != 2 or len(self.centroids) == 0:
            raise ValueError("El vocabulario debe ser una matriz (K, D)")
        self.idf = None if idf is None else np.asarray(idf, dtype=np.float64)
        if self.idf is not None and self.idf.shape != (self.k,):
            raise ValueError("El IDF debe tener un valor por palabra")
        self.kind = kind
        self.documents = documents
        self._quantizer = KMeans(k=self.k)
        self._quantizer.centroids = self.centroids

    @property
    def k(self) -> int:
        return len(self.centroids)

    @property
    def dimension(self) -> int:
        return self.centroids.shape[1]

    @classmethod
    def train(cls, descriptor_sets: Sequence[np.ndarray], k: int = DEFAULT_K, *,
              sample: int = DEFAULT_SAMPLE, seed: int = 42, max_iter: int = 50, kind: str = "") -> "BagOfWords":
        """Entrena el vocabulario con descriptores muestreados y el IDF con todos los archivos."""
        training = sample_descriptors(descriptor_sets, sample, seed)
        kmeans = KMeans(k=k, max_iter=max_iter, random_state=seed).fit(training)
        bow = cls(kmeans.centroids, kind=kind)
        histograms = [bow.histogram(d) for d in descriptor_sets]
        bow.idf = idf_from(histograms)
        bow.documents = len(histograms)
        return bow

    def histogram(self, descriptors: np.ndarray) -> np.ndarray:
        """Cuántos descriptores caen en cada palabra (asignación 1-NN)."""
        descriptors = np.asarray(descriptors, dtype=np.float64)
        if len(descriptors) == 0:
            return np.zeros(self.k, dtype=np.float64)
        if descriptors.ndim != 2 or descriptors.shape[1] != self.dimension:
            raise ValueError(f"Se esperaban descriptores de dimensión {self.dimension}")
        labels = self._quantizer.predict(descriptors)
        return np.bincount(labels, minlength=self.k).astype(np.float64)

    def transform(self, descriptors: np.ndarray) -> np.ndarray:
        """Vector TF-IDF normalizado de dimensión K para un archivo."""
        if self.idf is None:
            raise ValueError("El vocabulario no tiene IDF; entrénalo con BagOfWords.train")
        return tf_idf(self.histogram(descriptors), self.idf)

    def save(self, path: str | Path) -> None:
        if self.idf is None:
            raise ValueError("No se puede guardar un vocabulario sin IDF")
        np.savez(path, version=FORMAT_VERSION, centroids=self.centroids, idf=self.idf,
                 kind=self.kind, documents=self.documents)

    @classmethod
    def load(cls, path: str | Path) -> "BagOfWords":
        with np.load(path, allow_pickle=False) as data:
            if int(data["version"]) != FORMAT_VERSION:
                raise ValueError(f"Versión de vocabulario no soportada: {path}")
            return cls(data["centroids"], data["idf"], kind=str(data["kind"]), documents=int(data["documents"]))


def train_from_files(paths: Iterable[str], describe, k: int = DEFAULT_K, **options) -> BagOfWords:
    """Entrena un vocabulario con los descriptores locales que `describe` extrae de cada archivo."""
    return BagOfWords.train([describe(path) for path in paths], k, **options)
