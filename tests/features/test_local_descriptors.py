"""Descriptores locales: todos los puntos SIFT de una imagen y un MFCC por ventana."""

import numpy as np
import pytest

from engine.features.audio import MFCCExtractor
from engine.features.image import SIFTExtractor


class TestSIFTDescriptors:
    def test_one_descriptor_per_keypoint(self):
        image = np.random.default_rng(0).integers(0, 255, (200, 200), dtype=np.uint8)
        descriptors = SIFTExtractor().extract_descriptors(image)
        assert descriptors.ndim == 2 and descriptors.shape[1] == 128
        assert len(descriptors) > 1
        assert descriptors.dtype == np.float32

    def test_average_is_the_mean_of_the_local_descriptors(self):
        image = np.random.default_rng(1).integers(0, 255, (200, 200), dtype=np.uint8)
        extractor = SIFTExtractor()
        np.testing.assert_allclose(extractor.extract(image), extractor.extract_descriptors(image).mean(axis=0),
                                   rtol=1e-5)

    def test_low_contrast_image_retries_with_a_lower_threshold(self):
        rng = np.random.default_rng(2)
        image = (120 + rng.integers(0, 4, (200, 200))).astype(np.uint8)
        extractor = SIFTExtractor(contrast_threshold=0.5)
        assert len(extractor.extract_descriptors(image)) > 0

    def test_image_without_keypoints_has_no_descriptors(self):
        descriptors = SIFTExtractor().extract_descriptors(np.full((100, 100), 128, dtype=np.uint8))
        assert descriptors.shape == (0, 128)

    def test_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            SIFTExtractor().extract_descriptors(tmp_path / "no_existe.jpg")


class TestMFCCFrames:
    def test_one_vector_per_window(self):
        rate = 22050
        audio = np.sin(2 * np.pi * 440 * np.arange(rate * 2) / rate).astype(np.float32)
        frames = MFCCExtractor().extract_frames(audio)
        assert frames.shape[1] == 13
        assert len(frames) == 1 + len(audio) // 512  # salto por defecto de librosa
        assert frames.dtype == np.float32

    def test_long_audio_is_cut(self):
        rate = 22050
        audio = np.zeros(rate * 10, dtype=np.float32) + 0.1
        assert len(MFCCExtractor().extract_frames(audio, max_duration=1.0)) == 1 + rate // 512

    def test_empty_audio(self):
        with pytest.raises(ValueError):
            MFCCExtractor().extract_frames(np.array([], dtype=np.float32))
