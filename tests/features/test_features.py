"""
Tests unitarios para extractores de features (SIFT y MFCC).
"""

import pytest
import numpy as np
import cv2
import tempfile
from pathlib import Path
from engine.features.image import SIFTExtractor
from engine.features.audio import MFCCExtractor


class TestSIFTExtractor:

    def test_descriptor_dimensions(self):
        """Test que SIFT produce vectores de 128D."""
        extractor = SIFTExtractor()

        # Crear imagen sintética con suficiente contraste
        img = np.random.randint(0, 255, (200, 200), dtype=np.uint8)

        descriptor = extractor.extract(img)
        assert descriptor.shape == (128,), f"Esperado 128D, obtenido {descriptor.shape}"

    def test_no_descriptors_raises_error(self):
        """Test que lanza error cuando no hay features (imagen uniforme)."""
        extractor = SIFTExtractor(contrast_threshold=1.0)  # Umbral muy alto

        # Imagen uniforme (sin features)
        img = np.ones((100, 100), dtype=np.uint8) * 128

        with pytest.raises(ValueError, match="No se detectaron features"):
            extractor.extract(img)

    def test_cache_saves_to_disk(self):
        """Test que el cache funciona correctamente."""
        with tempfile.TemporaryDirectory() as tmpdir:
            extractor = SIFTExtractor(cache_dir=tmpdir)

            # Crear imagen temporal
            img_path = Path(tmpdir) / "test.jpg"
            img = np.random.randint(0, 255, (200, 200), dtype=np.uint8)
            cv2.imwrite(str(img_path), img)

            # Primera extracción (calcula y guarda en cache)
            desc1 = extractor.extract_with_cache(str(img_path))

            # Segunda extracción (debe leer del cache)
            desc2 = extractor.extract_with_cache(str(img_path))

            np.testing.assert_array_equal(desc1, desc2)

    def test_file_not_found(self):
        """Test que lanza error con archivo inexistente."""
        extractor = SIFTExtractor()

        with pytest.raises(FileNotFoundError):
            extractor.extract("imagen_inexistente.jpg")


class TestMFCCExtractor:

    def test_descriptor_dimensions(self):
        """Test que MFCC produce vectores de n_mfcc dimensiones."""
        extractor = MFCCExtractor(n_mfcc=13)

        # Audio sintético (ruido blanco)
        audio = np.random.randn(22050).astype(np.float32)

        descriptor = extractor.extract(audio)
        assert descriptor.shape == (13,), f"Esperado 13D, obtenido {descriptor.shape}"

    def test_audio_normalization(self):
        """Test que normaliza duración correctamente (trunca o rellena)."""
        extractor = MFCCExtractor(duration=1.0, sample_rate=22050)

        # Audio más largo que 1 segundo (2 segundos)
        audio_long = np.random.randn(44100).astype(np.float32)
        desc_long = extractor.extract(audio_long)
        assert desc_long.shape == (13,)

        # Audio más corto que 1 segundo (0.5 segundos)
        audio_short = np.random.randn(11025).astype(np.float32)
        desc_short = extractor.extract(audio_short)
        assert desc_short.shape == (13,)

    def test_no_mfccs_raises_error(self):
        """Test que lanza error cuando no hay MFCCs (audio vacío)."""
        extractor = MFCCExtractor()

        # Audio vacío
        audio = np.array([], dtype=np.float32)

        with pytest.raises(ValueError):
            extractor.extract(audio)