"""
Extractor de características SIFT para imágenes.
"""

import cv2
import numpy as np
from pathlib import Path
from typing import Union, Tuple, Optional

from engine.features.base import BaseFeatureExtractor


class SIFTExtractor(BaseFeatureExtractor):
    """
    Extractor SIFT que convierte imágenes en vectores de dimensión fija (128D)
    para su indexación en motores vectoriales como HNSW.
    """
    
    DESCRIPTOR_DIM = 128
    
    def __init__(
        self,
        n_features: int = 500,
        contrast_threshold: float = 0.04,
        image_size: Tuple[int, int] = (512, 512),
        cache_dir: Optional[Union[str, Path]] = None,
    ):
        super().__init__(cache_dir=cache_dir)
        self.sift = cv2.SIFT_create(
            nfeatures=n_features,
            contrastThreshold=contrast_threshold
        )
        self.image_size = image_size
        self.n_features = n_features
    
    def get_descriptor_dim(self) -> int:
        return self.DESCRIPTOR_DIM
    
    # Umbrales de contraste que se prueban, en orden, para imágenes con pocos puntos clave.
    RETRY_CONTRAST = (0.01, 0.0)

    def _load(self, image: Union[str, Path, np.ndarray]) -> np.ndarray:
        """Imagen en escala de grises con el tamaño normalizado."""
        if isinstance(image, (str, Path)):
            img_path = Path(image)
            if not img_path.exists():
                raise FileNotFoundError(f"Imagen no encontrada: {img_path}")
            img = cv2.imread(str(img_path), cv2.IMREAD_GRAYSCALE)
        else:
            img = image
            if img is not None and len(img.shape) == 3:
                img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        if img is None:
            raise ValueError("No se pudo cargar la imagen")
        return cv2.resize(img, self.image_size, interpolation=cv2.INTER_AREA)

    def extract_descriptors(self, image: Union[str, Path, np.ndarray]) -> np.ndarray:
        """
        Descriptores locales SIFT de la imagen: matriz (N, 128), uno por punto clave.

        Si no hay puntos clave, se reintenta con umbrales de contraste más bajos.
        Una imagen sin ningún punto (por ejemplo, de un solo color) devuelve (0, 128).
        """
        img = self._load(image)
        _, descriptors = self.sift.detectAndCompute(img, None)
        for threshold in self.RETRY_CONTRAST:
            if descriptors is not None and len(descriptors):
                break
            retry = cv2.SIFT_create(nfeatures=self.n_features, contrastThreshold=threshold)
            _, descriptors = retry.detectAndCompute(img, None)
        if descriptors is None:
            return np.empty((0, self.DESCRIPTOR_DIM), dtype=np.float32)
        return descriptors.astype(np.float32)

    def extract(self, image: Union[str, Path, np.ndarray]) -> np.ndarray:
        """
        Extrae descriptores SIFT y retorna el vector promedio (128D).
        """
        if isinstance(image, (str, Path)):
            img_path = Path(image)
            if not img_path.exists():
                raise FileNotFoundError(f"Imagen no encontrada: {img_path}")
            img = cv2.imread(str(img_path), cv2.IMREAD_GRAYSCALE)
        else:
            img = image
            if len(img.shape) == 3:
                img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        if img is None:
            raise ValueError(f"No se pudo cargar la imagen")
        
        img = cv2.resize(img, self.image_size, interpolation=cv2.INTER_AREA)
        
        keypoints, descriptors = self.sift.detectAndCompute(img, None)
        
        if descriptors is None or len(descriptors) == 0:
            raise ValueError("No se detectaron features SIFT en la imagen")
        
        return np.mean(descriptors, axis=0).astype(np.float32)

    def extract_to_fixed_vector(
        self, 
        image: Union[str, Path, np.ndarray], 
        method: str = "average"
    ) -> np.ndarray:
        if method == "average":
            return self.extract(image)
        else:
            raise ValueError(f"Método '{method}' no soportado. Usa 'average'.")
