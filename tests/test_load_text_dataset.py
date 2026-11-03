import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from benchmarks.generate_text_datasets import documents, generate
from benchmarks.load_text_dataset import load_dataset, schema
from engine.indexes.spimi import SpimiIndex
from engine.storage.heap_file import HeapFile
from engine.storage.text_store import TextStore
from frontend.motor import Motor


class TestLoadTextDataset(unittest.TestCase):
    def test_persistent_storage_preserves_text_and_search(self):
        with tempfile.TemporaryDirectory() as temp, ExitStack() as resources:
            root = Path(temp)
            generate(root / "data", sizes=(48,))
            result = load_dataset(root / "data/noticias_48.csv", root / "db")
            self.assertEqual(result["documents"], 48)
            texts = TextStore(str(root / "db/noticias.text"))
            resources.callback(texts.close)
            storage = HeapFile(str(root / "db/noticias.db"), schema(texts))
            resources.callback(storage.close)
            self.assertEqual([row for _, row in storage.scan()], list(documents(48)))
            index = SpimiIndex(str(root / "db/noticias.spimi"))
            resources.callback(index.close)
            self.assertEqual(index.doc_count, 48)
            for rank in (index.rank_tfidf, index.rank_bm25):
                matches = rank("inflación precios alimentos", 10)
                self.assertTrue(matches)
                self.assertTrue(all(storage.get(rid) is not None for rid, _ in matches))
            with self.assertRaises(FileExistsError):
                load_dataset(root / "data/noticias_48.csv", root / "db")

    def test_invalid_input_does_not_create_storage(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "bad.csv").write_text("wrong\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_dataset(root / "bad.csv", root / "db")
            self.assertFalse((root / "db").exists())

    def test_sql_script_loads_identical_rows_in_frontend(self):
        with tempfile.TemporaryDirectory(prefix="text's-") as temp:
            root = Path(temp)
            generate(root / "data", sizes=(12,))
            with patch("frontend.motor.DEMO_DIR", str(root / "demo")):
                motor = Motor()
                try:
                    sql = (root / "data/cargar_motor_12.sql").read_text(encoding="utf-8")
                    result = motor.ejecutar(sql)
                    self.assertFalse(result.tiene_error, result.error)
                    actual = [row for _, row in motor.catalog.table("noticias_12").storage.scan()]
                    self.assertEqual(actual, list(documents(12)))
                    result = motor.ejecutar("SELECT id, SCORE() FROM noticias_12 "
                                           "WHERE MATCH(contenido, 'inflación') USING BM25 LIMIT 10")
                    self.assertFalse(result.tiene_error, result.error)
                    self.assertTrue(result.filas)
                finally:
                    motor.cerrar()
