import csv
import json
import tempfile
import unittest
from pathlib import Path

from benchmarks.generate_text_datasets import digest, documents, generate
from benchmarks.text_queries import queries
from benchmarks.text_relevance import is_relevant
from benchmarks.text_validation import read_documents, validate_bundle
from engine.text.preprocessing import tokens


class TestTextDatasets(unittest.TestCase):
    def test_integrity_checker_rejects_tampering_and_wrong_judgments(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "data"
            metadata = generate(root, sizes=(12, 24))
            summary = validate_bundle(root)
            self.assertEqual(summary[12]["relevant_per_query"]["q01"], 2)
            path = root / "qrels_12.csv"
            path.write_text(path.read_text(encoding="utf-8").replace("q01,1,1", "q01,2,1"), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Checksum"):
                validate_bundle(root)
            metadata["files"][path.name]["sha256"] = digest(path)
            (root / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Juicio"):
                validate_bundle(root)

    def test_nested_deterministic_and_variable_documents(self):
        small = list(documents(24))
        self.assertEqual(small, list(documents(48))[:24])
        self.assertEqual(small, list(documents(24)))
        self.assertNotEqual(small, list(documents(24, seed=43)))
        self.assertEqual(len({row["contenido"] for row in small}), 24)
        self.assertGreater(max(len(row["contenido"].encode()) for row in documents(100)), 4096)
        self.assertEqual(len({row["tema"] for row in small}), 12)

    def test_query_groups_survive_preprocessing(self):
        workload = queries()
        self.assertEqual({q["words"] for q in workload}, {1, 3, 6})
        self.assertEqual(len({q["query_id"] for q in workload}), 30)
        for query in workload:
            self.assertEqual(len(query["text"].split()), query["words"])
            self.assertEqual(len(tokens(query["text"])), query["words"])

    def test_qrels_follow_intent_not_shared_words(self):
        rows = list(documents(12))
        # El primer documento de inflación menciona seguridad como noticia secundaria.
        security = next(q for q in queries() if q["topic"] == "seguridad")
        self.assertIn("seguridad", rows[0]["contenido"])
        self.assertFalse(is_relevant(rows[0], security))
        self.assertTrue(is_relevant(rows[3], security))

    def test_generated_artifacts_and_qrels_scope(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = generate(root / "a", sizes=(12, 24))
            second = generate(root / "b", sizes=(12, 24))
            self.assertEqual(manifest, second)
            for size in (12, 24):
                docs = list(read_documents(root / "a" / f"noticias_{size}.csv"))
                self.assertEqual(docs, list(documents(size)))
                with (root / "a" / f"qrels_{size}.csv").open(newline="", encoding="utf-8") as stream:
                    qrels = list(csv.DictReader(stream))
                self.assertEqual(len(qrels), size * 3)
                actual = {(q["query_id"], int(q["doc_id"])) for q in qrels}
                self.assertEqual(len(actual), len(qrels))
                expected = {(q["query_id"], d["id"]) for q in queries() for d in docs if is_relevant(d, q)}
                self.assertEqual(actual, expected)
            with self.assertRaises(FileExistsError):
                generate(root / "a", sizes=(12,))

    def test_invalid_sizes_and_csv(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "data"
            for sizes in ((), (0,), (-1,), (12, 12)):
                with self.assertRaises(ValueError):
                    generate(path, sizes=sizes)
                self.assertFalse(path.exists())
            for data in ("id,contenido\n1,test\n",
                         "id,url,contenido,categoria,tema\n2,u,c,t,s\n",
                         "id,url,contenido,categoria,tema\n1,u,,t,s\n"):
                path.write_text(data, encoding="utf-8")
                with self.assertRaises(ValueError):
                    list(read_documents(path))
