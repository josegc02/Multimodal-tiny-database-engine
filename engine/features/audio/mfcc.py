"""
Extractor MFCC para audio usando librosa.
"""

import librosa
import numpy as np
from pathlib import Path
from typing import Union
from ..base import BaseFeatureExtractor


class MFCCExtractor(BaseFeatureExtractor):

    def __init__(
            self,
            n_mfcc: int = 13,
            sample_rate: int = 22050,  # Normalización
            duration: float = 5.0,  # Duración fija en segundos
            cache_dir: Union[str, Path, None] = None
    ):
        super().__init__(cache_dir)
        self.n_mfcc = n_mfcc
        self.sample_rate = sample_rate
        self.duration = duration

    def normalize_audio(self, y: np.ndarray) -> np.ndarray:
        """Normaliza duración del audio."""
        target_samples = int(self.sample_rate * self.duration)

        if len(y) > target_samples:
            # Truncar si es más largo
            y = y[:target_samples]
        elif len(y) < target_samples:
            # Rellenar con ceros si es más corto
            padding = target_samples - len(y)
            y = np.pad(y, (0, padding), mode='constant')

        return y

    def _load(self, audio: Union[str, Path, np.ndarray]) -> np.ndarray:
        if isinstance(audio, (str, Path)):
            audio_path = Path(audio)
            if not audio_path.exists():
                raise FileNotFoundError(f"Audio no encontrado: {audio_path}")
            y, _ = librosa.load(str(audio_path), sr=self.sample_rate)
        else:
            y = np.asarray(audio, dtype=np.float32)
        if len(y) == 0:
            raise ValueError("El audio está vacío, no se pueden extraer MFCCs")
        return y

    def extract_frames(self, audio: Union[str, Path, np.ndarray],
                       max_duration: float = 30.0) -> np.ndarray:
        """
        Descriptores locales de audio: matriz (T, n_mfcc), un vector MFCC por ventana.

        A diferencia de extract(), no rellena ni promedia: cada ventana deslizante
        es un descriptor, como los puntos clave de SIFT. Se analizan como máximo
        `max_duration` segundos para acotar el costo con audios largos.
        """
        y = self._load(audio)[:int(self.sample_rate * max_duration)]
        mfccs = librosa.feature.mfcc(y=y, sr=self.sample_rate, n_mfcc=self.n_mfcc)
        return mfccs.T.astype(np.float32)

    def extract(self, audio: Union[str, Path, np.ndarray]) -> np.ndarray:

        # Cargar audio
        if isinstance(audio, (str, Path)):
            audio_path = Path(audio)
            if not audio_path.exists():
                raise FileNotFoundError(f"Audio no encontrado: {audio_path}")
            y, sr = librosa.load(str(audio_path), sr=self.sample_rate)
        else:
            y = audio
            sr = self.sample_rate

        if len(y) == 0:
            raise ValueError("El audio está vacío, no se pueden extraer MFCCs")

        # Normalizar duración
        y = self.normalize_audio(y)

        # Extraer MFCCs
        mfccs = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=self.n_mfcc)

        if mfccs is None or mfccs.shape[1] == 0:
            raise ValueError("No se pudieron extraer MFCCs del audio")

        # Promediar sobre el tiempo (axis=1) para obtener un vector fijo
        return np.mean(mfccs, axis=1).astype(np.float32)

    def get_descriptor_dim(self) -> int:
        return self.n_mfcc