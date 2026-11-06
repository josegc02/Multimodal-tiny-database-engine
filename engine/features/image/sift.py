"""
Extractor SIFT para imágenes con normalización y caching.
"""

import cv2
import numpy as np
from pathlib import Path
from typing import Union, Tuple
from ..base import BaseFeatureExtractor


class SIFTExtractor(BaseFeatureExtractor):

    DESCRIPTOR_DIM = 128

    def __init__(
            self,
            n_features: int = 500,
            contrast_threshold: float = 0.04,
            image_size: Tuple[int, int] = (512, 512),  # Normalización
            cache_dir: Union[str, Path, None] = None
    ):
        super().__init__(cache_dir)
        self.sift = cv2.SIFT_create(
            nfeatures=n_features,
            contrastThreshold=contrast_threshold
        )
        self.image_size = image_size

    def normalize_image(self, img: np.ndarray) -> np.ndarray:
        """Normaliza el tamaño de la imagen."""
        return cv2.resize(img, self.image_size, interpolation=cv2.INTER_AREA)

    def extract(self, image: Union[str, Path, np.ndarray]) -> np.ndarray:

        # Cargar imagen
        if isinstance(image, (str, Path)):
            
            image_path = Path(image)
            if not image_path.exists():
                raise FileNotFoundError(f"Imagen no encontrada: {image_path}")
            img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
        else:
            img = image
            if len(img.shape) == 3:
                img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        if img is None:
            raise ValueError("No se pudo cargar la imagen")

        # Normalizar tamaño
        img = self.normalize_image(img)

        # Extraer features
        keypoints, descriptors = self.sift.detectAndCompute(img, None)

        if descriptors is None or len(descriptors) == 0:
            raise ValueError(
                f"No se detectaron features SIFT. "
                f"Intenta reducir contrast_threshold o usar otra imagen."
            )

        # Retornar promedio (vector de dimensión fija)
        return np.mean(descriptors, axis=0).astype(np.float32)

    def get_descriptor_dim(self) -> int:
        return self.DESCRIPTOR_DIM