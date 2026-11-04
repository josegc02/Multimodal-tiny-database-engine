"""
Extractor de características SIFT para imágenes.
"""

import cv2
import numpy as np
from pathlib import Path
from typing import Union, Tuple, Optional

from engine.features.base import BaseExtractor


class SIFTExtractor(BaseExtractor):
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