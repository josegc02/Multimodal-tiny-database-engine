import json
import os
import tempfile
import unittest
from pathlib import Path

from benchmarks.bench_text import run_worker
from benchmarks.generate_text_datasets import generate


class TestTextWorkers(unittest.TestCase):
    def request(self, directory, technique):
        return {"dataset_dir": str(directory), "size": 24, "technique": technique,
                "repetition": 1, "seed": 42, "dsn": os.environ.get("TEXT_POSTGRES_TEST_DSN"),
                "container": os.environ.get("TEXT_POSTGRES_TEST_CONTAINER", "bd2-texto-postgres-1")}

    def test_engine_workers_report_real_measurements(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / "data"
            generate(directory, sizes=(24,))
            for technique in ("TF-IDF", "BM25"):
                result = run_worker(self.request(directory, technique))
                self.assertEqual(len(result["samples"]), 30)
                self.assertGreater(result["build_seconds"], 0)
                self.assertGreater(result["total_bytes"], result["index_bytes"])
                self.assertGreaterEqual(result["rss_peak_bytes"], result["rss_initial_bytes"])
                for row in result["samples"]:
                    self.assertGreaterEqual(row["precision"], 0)
                    self.assertLessEqual(row["recall"], 1)
                    self.assertGreater(row["postings_read"], 0)

    @unittest.skipUnless(os.environ.get("TEXT_POSTGRES_TEST_DSN"), "requiere PostgreSQL y Docker")
    def test_postgres_worker_uses_server_memory_and_cleans_temp_table(self):
        from postgres_text.client import connect

        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / "data"
            generate(directory, sizes=(24,))
            result = run_worker(self.request(directory, "GIN"))
            self.assertEqual(result["memory_scope"], "postgres_backend")
            self.assertGreater(result["rss_peak_bytes"], 0)
            self.assertEqual(len(result["plans"]), 30)
            self.assertTrue(all(row["postings_read"] is None for row in result["samples"]))
            with connect(os.environ["TEXT_POSTGRES_TEST_DSN"]) as connection:
                count = connection.execute("SELECT count(*) FROM pg_class WHERE relname='bench_news'").fetchone()[0]
                self.assertEqual(count, 0)
