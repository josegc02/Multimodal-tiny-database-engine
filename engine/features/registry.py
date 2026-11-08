"""ExtractFeatures: el vector que guarda el motor para cada valor IMAGE o AUDIO.

Sigue el pipeline del enunciado (2.4.1) y de la clase 11:

1. Descriptores locales: todos los puntos SIFT de la imagen, o un MFCC por
   ventana del audio.
2. Cuantización con el vocabulario Bag of Visual/Audio Words entrenado con
   K-Means (models/bow_image_k1024.npz y models/bow_audio_k256.npz,
   scripts/train_codebook.py).
3. Histograma con TF-IDF y normalización L2: un vector de dimensión K
   (1024 para imágenes, 256 para audio).

Imágenes usan K = 1024: con K = 256 cada imagen activaba ~200 de las 256
palabras y los histogramas se parecían todos; mezclada entre 5000 fotos de
COCO, una foto recortada o girada encontraba su original primero solo en el
92 % de los casos (100 % con K = 1024). K = 2048 apenas mejora eso y duplica
la memoria de los índices. Detalles en la sección de la Parte 4 del informe.

Un archivo sin descriptores (una imagen de un solo color) da el vector nulo.
`register_extractor` permite usar otro pipeline (por ejemplo, en los tests).

OpenCV y librosa se importan recién al extraer el primer vector: una tabla sin
columnas multimedia no los necesita.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Dict

import numpy as np

MEDIA_TYPES = ("image", "audio")
MODELS_DIR = Path(__file__).resolve().parents[2] / "models"

Extractor = Callable[[str], np.ndarray]

_extractors: Dict[str, Extractor] = {}
_latch = threading.Lock()


VOCABULARY_K = {"image": 1024, "audio": 256}


def local_describer(kind: str) -> Callable[[str], np.ndarray]:
    """Descriptores locales de un archivo: SIFT por punto clave (imagen) o MFCC por ventana (audio).

    El entrenamiento del vocabulario, la inserción y el benchmark usan esta
    misma función, así los descriptores siempre caen en el mismo espacio.
    """
    if kind == "image":
        from engine.features.image.sift import SIFTExtractor
        return SIFTExtractor(n_features=500).extract_descriptors
    if kind == "audio":
        from engine.features.audio.mfcc import MFCCExtractor
        return MFCCExtractor().extract_frames
    raise ValueError(f"Tipo multimedia no soportado: {kind}")


def _default(kind: str) -> Extractor:
    from engine.features.bow import BagOfWords

    path = vocabulary_path(kind)
    if not path.exists():
        source = "--input datasets/bow_training/coco" if kind == "image" else "--input datasets/bow_training/esc50"
        raise FileNotFoundError(f"Falta el vocabulario {path}; entrénalo con "
                                f"python scripts/train_codebook.py --kind {kind} {source}")
    vocabulary = BagOfWords.load(path)
    describe = local_describer(kind)
    return lambda file: vocabulary.transform(describe(file))


def vocabulary_path(kind: str, k: int | None = None) -> Path:
    """Archivo del vocabulario Bag of Words de un tipo multimedia (por defecto, el que usa el motor)."""
    return MODELS_DIR / f"bow_{kind}_k{VOCABULARY_K[kind] if k is None else k}.npz"


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
