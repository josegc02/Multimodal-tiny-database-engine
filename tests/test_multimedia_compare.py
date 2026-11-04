import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from benchmarks.multimedia_compare import exact_neighbors, run_trial


class TestMultimediaCompare(unittest.TestCase):
    def test_trial_uses_exact_neighbors_and_real_measurements(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "images").mkdir()
            names = [f"image_{i}.jpg" for i in range(24)]
            for name in names:
                (root / "images" / name).touch()
            (root / "instances_subset.json").write_text(json.dumps({
                "images": [{"id": i, "file_name": name} for i, name in enumerate(names)]
            }), encoding="utf-8")
            (root / "queries.json").write_text(json.dumps({"queries": [
                {"query_file": names[i], "category_name": "test"} for i in range(3)
            ]}), encoding="utf-8")
            rng = np.random.default_rng(42)
            vectors = rng.random((24, 8)).astype(np.float32)
            cache = root / "vectors.npz"
            np.savez(cache, vectors=vectors, filenames=np.asarray(names))
            for metric in ("euclidean", "cosine"):
                exact = exact_neighbors(vectors, vectors[0], 0, metric)
                self.assertEqual(len(exact), 10)
                self.assertNotIn(0, exact)
                for technique in ("IVF", "HNSW"):
                    with self.subTest(metric=metric, technique=technique):
                        summary, rows = run_trial(root, 24, metric, technique, cache)
                        self.assertEqual(len(rows), 3)
                        self.assertGreater(summary["build_seconds"], 0)
                        self.assertGreater(summary["rss_peak_bytes"], 0)
                        for row in rows:
                            self.assertEqual(len(row["exact_files"]), 10)
                            self.assertNotIn(row["query_file"], row["found_files"])
                            self.assertGreaterEqual(row["recall_at_10"], 0)
                            self.assertLessEqual(row["recall_at_10"], 1)


if __name__ == "__main__":
    unittest.main()
