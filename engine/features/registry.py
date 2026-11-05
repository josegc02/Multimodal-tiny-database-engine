"""Extractor que usa el motor para cada tipo de columna multimedia.

IMAGE usa el promedio de los descriptores SIFT (128 dimensiones) y AUDIO el
promedio de los coeficientes MFCC (13 dimensiones), igual que la comparación
experimental de #59. Para cambiar el pipeline (por ejemplo, a Bag of Visual
Words) basta con registrar otra función con `register_extractor`.

OpenCV y librosa se importan recién al extraer el primer vector: una tabla sin
columnas multimedia no los necesita.
"""

from __future__ import annotations

import threading
from typing import Callable, Dict

import numpy as np

MEDIA_TYPES = ("image", "audio")

Extractor = Callable[[str], np.ndarray]

_extractors: Dict[str, Extractor] = {}
_latch = threading.Lock()


def _default(kind: str) -> Extractor:
    if kind == "image":
        from engine.features.image.sift import SIFTExtractor
        return SIFTExtractor().extract
    from engine.features.audio.mfcc import MFCCExtractor
    return MFCCExtractor().extract


def register_extractor(kind: str, extractor: Extractor) -> None:
    """Reemplaza el extractor de un tipo multimedia."""
    if kind not in MEDIA_TYPES:
        raise ValueError(f"Tipo multimedia no soportado: {kind}")
    with _latch:
        _extractors[kind] = extractor


def extractor_for(kind: str) -> Extractor:
    """Función que convierte la ruta de un archivo en su vector."""
    if kind not in MEDIA_TYPES:
        raise ValueError(f"Tipo multimedia no soportado: {kind}")
    with _latch:
        if kind not in _extractors:
            _extractors[kind] = _default(kind)
        return _extractors[kind]


def extract_features(kind: str, path: str) -> np.ndarray:
    """ExtractFeatures(objeto): vector 1D de números finitos para el archivo."""
    vector = np.asarray(extractor_for(kind)(path), dtype=np.float32)
    if vector.ndim != 1 or len(vector) == 0 or not np.isfinite(vector).all():
        raise ValueError("El extractor debe devolver un vector 1D de números finitos")
    return vector
