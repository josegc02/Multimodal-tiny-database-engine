import hashlib
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Union
import numpy as np


class BaseFeatureExtractor(ABC):

    def __init__(self, cache_dir: Optional[Union[str, Path]] = None):
        """
        Args:
            cache_dir: Directorio para guardar descriptores calculados.
                      Si es None, no se usa cache.
        """
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    @abstractmethod
    def extract(self, data: Union[str, Path, np.ndarray]) -> np.ndarray:
        """Extrae descriptores de los datos."""
        pass

    @abstractmethod
    def get_descriptor_dim(self) -> int:
        """Retorna la dimensión fija del descriptor."""
        pass

    def _get_cache_path(self, data: Union[str, Path, np.ndarray]) -> Path:
        """Genera ruta de cache basada en hash del contenido."""
        if isinstance(data, (str, Path)):
            # Hash del contenido del archivo
            with open(data, 'rb') as f:
                content = f.read()
        else:
            # Hash del array numpy
            content = data.tobytes()

        hash_key = hashlib.md5(content).hexdigest()
        return self.cache_dir / f"{hash_key}.npy"

    def extract_with_cache(self, data: Union[str, Path, np.ndarray]) -> np.ndarray:
        """
        Extrae descriptores usando cache si está disponible.
        """
        if self.cache_dir:
            cache_path = self._get_cache_path(data)
            if cache_path.exists():
                return np.load(cache_path)

        # Extraer y guardar en cache
        descriptor = self.extract(data)

        if self.cache_dir:
            cache_path = self._get_cache_path(data)
            np.save(cache_path, descriptor)

        return descriptor