import random
import tempfile
import unittest
from pathlib import Path

from engine.indexes import BPlusTree, BPlusTreeClustered
from tests.indexes.test_bplus_tree import check_tree


class TestClusteredRecords(unittest.TestCase):
    def test_records_move_with_splits_merges_and_persist(self):
        schema = [("id", "int"), ("nombre", "str", 16), ("valor", "float")]
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "data.bpt")
            expected = {i: {"id": i, "nombre": f"niño{i}", "valor": i / 2} for i in range(500)}
            keys = list(expected)
            random.Random(42).shuffle(keys)
            with BPlusTreeClustered(path, schema, "id", M=3, page_size=256) as tree:
                for key in keys:
                    self.assertTrue(tree.insert(expected[key]))
                self.assertFalse(tree.insert(expected[5]))
                check_tree(self, tree)
                self.assertEqual(tree.range_search(4, 8), [expected[k] for k in range(4, 9)])
                for key in keys[:350]:
                    self.assertTrue(tree.delete(key))
                    expected.pop(key)
                check_tree(self, tree)
            with BPlusTreeClustered(path, schema, "id") as tree:
                self.assertEqual(list(tree.scan()), [expected[k] for k in sorted(expected)])
                for key, record in expected.items():
                    self.assertEqual(tree.search(key), record)
                for key in list(expected):
                    tree.delete(key)
                self.assertEqual(list(tree.scan()), [])
                check_tree(self, tree)
            with self.assertRaises(ValueError):
                BPlusTree(path, schema, "id")  # Misma clave, distinto formato de hoja.
            with self.assertRaises(ValueError):
                BPlusTreeClustered(path, [("id", "int"), ("nombre", "str", 8)], "id")

    def test_utf8_float_keys_and_validation_before_writing(self):
        for kind, schema, records in (
            ("str", [("key", "str", 8)], [{"key": s} for s in ("z", "á", "niño", "a")]),
            ("float", [("key", "float")], [{"key": x} for x in (3.5, -2.5, 0.0, 1.0)]),
        ):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                path = str(Path(tmp) / "tree")
                with BPlusTreeClustered(path, schema, "key", M=2, page_size=128) as tree:
                    for record in records:
                        tree.insert(record)
                    before = list(tree.scan())
                    with self.assertRaises(ValueError):
                        tree.insert({"key": "é" * 8 if kind == "str" else float("nan")})
                    self.assertEqual(list(tree.scan()), before)
                    check_tree(self, tree)
                with BPlusTreeClustered(path, schema, "key") as tree:
                    self.assertEqual(list(tree.scan()), sorted(records, key=lambda r: r["key"]))
