import csv
import json
import tempfile
import unittest
from pathlib import Path

from benchmarks.bench_text import main
from benchmarks.generate_text_datasets import generate
from benchmarks.validate_text_results import validate
from benchmarks.text_workload import read_workload


class TestTextPipeline(unittest.TestCase):
    def test_query_shuffle_preserves_workload_and_judgments(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "data"
            generate(root, sizes=(24,))
            first, relevant = read_workload(root, 24, 42)
            second, other = read_workload(root, 24, 43)
            self.assertNotEqual(first, second)
            self.assertEqual(sorted(first, key=lambda q: q["query_id"]),
                             sorted(second, key=lambda q: q["query_id"]))
            self.assertEqual(relevant, other)

    def test_complete_local_run_and_corruption_detection(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            generate(root / "data", sizes=(24,))
            args = ["--dataset-dir", str(root / "data"), "--output", str(root / "out"),
                    "--sizes", "24", "--repetitions", "1", "--sin-postgres"]
            main(args)
            result = validate(root / "out", root / "data")
            self.assertEqual(result["runs"], 2)
            self.assertEqual(result["queries"], 60)
            with self.assertRaises(FileExistsError):
                main(args)
            path = root / "out/query_runs.csv"
            with path.open(newline="") as stream:
                reader = csv.DictReader(stream)
                fields, rows = reader.fieldnames, list(reader)
            rows[0]["precision"] = "999"
            with path.open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
            with self.assertRaisesRegex(ValueError, "Relevancia"):
                validate(root / "out", root / "data")

    def test_incomplete_output_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "metadata.json").write_text(json.dumps({"complete": False}))
            with self.assertRaisesRegex(ValueError, "incompleta"):
                validate(root, root)
