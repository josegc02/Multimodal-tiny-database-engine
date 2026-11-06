import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from benchmarks.multimedia_compare import exact_neighbors, run_trial
from benchmarks.multimedia_gallery import write_gallery
from benchmarks.multimedia_plots import plot_results
from benchmarks.multimedia_report import write_report


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

    def test_cosine_skips_null_vectors(self):
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
                {"query_file": names[i], "category_name": "test"} for i in (0, 1, 2)
            ]}), encoding="utf-8")
            vectors = np.random.default_rng(1).random((24, 8)).astype(np.float32)
            vectors[[1, 5]] = 0
            cache = root / "vectors.npz"
            np.savez(cache, vectors=vectors, filenames=np.asarray(names), features="bovw")
            for technique in ("IVF", "HNSW"):
                summary, rows = run_trial(root, 24, "cosine", technique, cache, "bovw")
                self.assertEqual((summary["excluded_vectors"], summary["skipped_queries"]), (2, 1))
                self.assertEqual(len(rows), 2)
                for row in rows:
                    self.assertNotIn(names[5], row["exact_files"] + row["found_files"])
            summary, rows = run_trial(root, 24, "euclidean", "HNSW", cache, "bovw")
            self.assertEqual((summary["excluded_vectors"], len(rows)), (0, 3))

    def test_reports_use_measured_data_and_existing_images(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "out"
            output.mkdir()
            image_dir = root / "datasets" / "coco1k" / "images"
            image_dir.mkdir(parents=True)
            (image_dir / "a.jpg").touch()
            records = []
            for metric in ("euclidean", "cosine"):
                for technique in ("IVF", "HNSW"):
                    records.append({"size": 1000, "metric": metric, "technique": technique,
                                    "queries": 1, "build_seconds": 1.0,
                                    "mean_query_seconds": 0.01, "mean_recall_at_10": 0.5,
                                    "rss_initial_bytes": 1024, "rss_peak_bytes": 2048})
            import csv
            with (output / "summary.csv").open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(records[0]))
                writer.writeheader()
                writer.writerows(records)
            (output / "queries.json").write_text(json.dumps([{
                "size": row["size"], "metric": row["metric"], "technique": row["technique"],
                "query_file": "a.jpg", "category": "test", "recall_at_10": 0.5,
                "found_files": ["a.jpg"], "exact_files": ["a.jpg"]
            } for row in records]), encoding="utf-8")
            plot_results(output)
            write_gallery(output, root / "datasets")
            write_report(output)
            self.assertIn("0.500", (output / "report.md").read_text(encoding="utf-8"))
            self.assertIn("a.jpg", (output / "gallery.html").read_text(encoding="utf-8"))
            for name in ("construction.png", "query.png", "recall.png", "memory.png"):
                self.assertGreater((output / name).stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
