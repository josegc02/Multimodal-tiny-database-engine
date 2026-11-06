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
            vectors = extract_vectors(root, names, cache)
            direct = SIFTExtractor(n_features=500)
            for name, vector in zip(names, vectors):
                np.testing.assert_allclose(vector, direct.extract(root / "images" / name))
            np.testing.assert_array_equal(extract_vectors(root, names, cache), vectors)

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
