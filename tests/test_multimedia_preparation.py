import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from benchmarks.multimedia_data import extract_vectors
from engine.features.image.sift import SIFTExtractor
from scripts import create_subsets


class TestMultimediaPreparation(unittest.TestCase):
    def test_featureless_image_uses_recorded_nonzero_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "images").mkdir()
            blank = np.zeros((128, 128), dtype=np.uint8)
            textured = np.random.default_rng(8).integers(0, 256, (128, 128), dtype=np.uint8)
            cv2.imwrite(str(root / "images/blank.jpg"), blank)
            cv2.imwrite(str(root / "images/textured.jpg"), textured)
            cache = root / "vectors.npz"
            vectors = extract_vectors(root, ["blank.jpg", "textured.jpg"], cache, "sift-mean")
            self.assertEqual(vectors.shape, (2, 128))
            self.assertGreater(np.linalg.norm(vectors[0]), 0)
            np.testing.assert_allclose(np.linalg.norm(vectors[0]), np.linalg.norm(vectors[1]), rtol=1e-5)
            with np.load(cache, allow_pickle=False) as saved:
                self.assertEqual(saved["fallback_files"].tolist(), ["blank.jpg"])

    def test_parallel_sift_keeps_order_and_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "images").mkdir()
            names = [f"{i}.jpg" for i in range(5)]
            rng = np.random.default_rng(7)
            for name in names:
                image = rng.integers(0, 256, (128, 128), dtype=np.uint8)
                self.assertTrue(cv2.imwrite(str(root / "images" / name), image))
            cache = root / "vectors.npz"
            vectors = extract_vectors(root, names, cache, "sift-mean")
            direct = SIFTExtractor(n_features=500)
            for name, vector in zip(names, vectors):
                np.testing.assert_allclose(vector, direct.extract(root / "images" / name))
            np.testing.assert_array_equal(extract_vectors(root, names, cache), vectors)

    def test_bovw_vectors_follow_extract_features(self):
        from engine.features.registry import extract_features

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "images").mkdir()
            rng = np.random.default_rng(3)
            cv2.imwrite(str(root / "images/textured.jpg"), rng.integers(0, 256, (128, 128), dtype=np.uint8))
            cv2.imwrite(str(root / "images/blank.jpg"), np.zeros((128, 128), dtype=np.uint8))
            cache = root / "vectors.npz"
            vectors = extract_vectors(root, ["textured.jpg", "blank.jpg"], cache, "bovw")
            self.assertEqual(vectors.shape, (2, 256))
            np.testing.assert_allclose(vectors[0], extract_features("image", str(root / "images/textured.jpg")),
                                       rtol=1e-5)
            self.assertFalse(vectors[1].any())
            with np.load(cache, allow_pickle=False) as saved:
                self.assertEqual(str(saved["features"]), "bovw")
                self.assertEqual(saved["empty_files"].tolist(), ["blank.jpg"])
            with self.assertRaisesRegex(ValueError, "bovw"):
                extract_vectors(root, ["textured.jpg", "blank.jpg"], cache, "sift-mean")

    def test_subset_falls_back_to_copy_if_hardlink_is_unavailable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            (source / "a.jpg").write_bytes(b"image")
            data = {"images": [{"id": 1, "file_name": "a.jpg"}],
                    "annotations": [{"image_id": 1}], "categories": []}
            with patch.object(create_subsets, "IMAGES_DIR", str(source)), \
                 patch.object(create_subsets.os, "link", side_effect=OSError("no hardlinks")):
                create_subsets.create_subset(data, 1, str(root / "subset"))
            self.assertEqual((root / "subset/images/a.jpg").read_bytes(), b"image")
            manifest = json.loads((root / "subset/instances_subset.json").read_text())
            self.assertEqual(len(manifest["images"]), 1)

    def test_subset_uses_hardlink_when_available(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            (source / "a.jpg").write_bytes(b"image")
            data = {"images": [{"id": 1, "file_name": "a.jpg"}],
                    "annotations": [], "categories": []}
            with patch.object(create_subsets, "IMAGES_DIR", str(source)):
                create_subsets.create_subset(data, 1, str(root / "subset"))
            self.assertEqual((root / "subset/images/a.jpg").read_bytes(), b"image")
            self.assertGreaterEqual((root / "subset/images/a.jpg").stat().st_nlink, 2)
