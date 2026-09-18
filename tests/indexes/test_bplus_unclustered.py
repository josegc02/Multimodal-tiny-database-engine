from collections import Counter
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

from engine.indexes import BPlusTreeClustered, BPlusTreeUnclustered
from engine.query import Catalog, IndexInfo, SQLExecutor, TableStats
from engine.query.external_algorithms import BufferConfig
from engine.storage.heap_file import HeapFile
from engine.storage.record import RID
from engine.storage.sequential_file import SequentialFile
from tests.indexes.test_bplus_tree import check_tree


SCHEMA = [("id", "int"), ("category", "str", 8), ("value", "float")]


class TestUnclusteredBPlus(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def index(self, name="index", **kwargs):
        index = BPlusTreeUnclustered(str(self.root / name), **kwargs)
        self.addCleanup(index.close)
        return index

    def test_duplicate_keys_random_deletes_and_invariants(self):
        for order in (2, 3, 5):
            index = self.index(str(order), order=order, page_size=128 if order < 5 else 256)
            expected = set()
            rng = random.Random(order)
            for step in range(1600):
                key, rid = rng.randrange(12), RID(rng.randrange(30), rng.randrange(3), rng.choice(("main", "aux")))
                pair = (key, rid)
                if rng.random() < .65:
                    self.assertEqual(index.insert(key, rid), pair not in expected)
                    expected.add(pair)
                else:
                    self.assertEqual(index.delete(key, rid), int(pair in expected))
                    expected.discard(pair)
                if step % 80 == 0:
                    check_tree(self, index.tree)
                    self.assertEqual(set(index.iter_range()), expected)
                    self.assertEqual(set(index.search(key)), {r for k, r in expected if k == key})
            for key in range(12):
                matches = {entry for entry in expected if entry[0] == key}
                self.assertEqual(index.delete(key), len(matches))
                expected -= matches
                check_tree(self, index.tree)
            self.assertEqual(list(index.iter_ordered()), [])

    def test_rid_encoding_reopen_ranges_and_reverse(self):
        index = self.index(order=3, page_size=128)
        entries = [(i % 7, RID(i, i % 3, "aux" if i % 2 else "main")) for i in range(120)]
        entries.append((6, RID((1 << 31) - 1, (1 << 31) - 1, "aux")))
        self.assertEqual(index.bulk_load(entries), len(entries))
        for bad in (RID(-1, 0), RID(1 << 31, 0), RID(0, 1 << 31), RID(0, 0, "bad"), RID(True, 0)):
            with self.assertRaises(ValueError):
                index.insert(1, bad)
        index.close()
        index = self.index()
        self.assertEqual(Counter(index.iter_range()), Counter(entries))
        self.assertEqual(set(index.range_search(2, 4, include_upper=False)), {r for k, r in entries if 2 <= k < 4})
        key_for = {rid: key for key, rid in entries}
        reverse = list(index.iter_ordered(reverse=True))
        self.assertEqual([key_for[r] for r in reverse], sorted(key_for.values(), reverse=True))
        self.assertEqual(Counter(reverse), Counter(key_for.keys()))
        self.assertEqual(set(index.search(3.0)), set(index.search(3)))
        self.assertEqual(index.search(3.5), [])

    def test_bulk_replace_failure_preserves_file_and_data(self):
        index = self.index()
        index.insert(1, RID(0, 1))
        original = (self.root / "index").read_bytes()
        def broken():
            yield 2, RID(0, 2)
            raise RuntimeError("Fuente interrumpida")
        with self.assertRaises(RuntimeError):
            index.bulk_load(broken(), replace=True)
        self.assertEqual((self.root / "index").read_bytes(), original)
        self.assertEqual(index.search(1), [RID(0, 1)])
        self.assertEqual(index.bulk_load([(2, RID(0, 2))] * 2, replace=True), 1)
        self.assertEqual(index.search(1), [])
        self.assertEqual(index.search(2), [RID(0, 2)])
        self.assertFalse(any(p.name.startswith(".bplus-build-") for p in self.root.iterdir()))

    def test_resolved_results_match_clustered_on_heap_and_sequential(self):
        records = [{"id": i, "category": f"c{i % 5}", "value": i / 2} for i in range(80)]
        clustered = BPlusTreeClustered(str(self.root / "clustered"), SCHEMA, "id", M=3, page_size=256)
        self.addCleanup(clustered.close)
        for record in reversed(records):
            clustered.insert(record)
        for kind in ("heap", "seq"):
            with self.subTest(storage=kind):
                path = str(self.root / kind)
                storage = (HeapFile(path, SCHEMA, page_size=128) if kind == "heap" else
                           SequentialFile(path + ".main", path + ".aux", SCHEMA, "id", page_size=128))
                self.addCleanup(storage.close)
                shuffled = list(records)
                random.Random(44).shuffle(shuffled)
                for record in shuffled:
                    storage.insert(record)
                index = self.index(kind + ".idx", key_type="str", key_size=8, order=3, page_size=128)
                index.bulk_load_from_storage(storage, "category")
                for category in ("c0", "c1", "c2", "c3", "c4", "absent"):
                    expected = [r for r in clustered.scan() if r["category"] == category]
                    self.assertEqual(sorted(index.search_records(category, storage), key=lambda r: r["id"]), expected)
                actual = [index.resolve(rid, storage) for rid in index.range_search("c1", "c3")]
                expected = [r for r in clustered.scan() if "c1" <= r["category"] <= "c3"]
                self.assertEqual(sorted(actual, key=lambda r: r["id"]), expected)
                rid = index.search("c2")[0]
                storage.delete(rid)
                self.assertIsNone(index.resolve(rid, storage))
                index.bulk_load_from_storage(storage, "category")
                self.assertNotIn(rid, index.search("c2"))

    def test_sql_cost_optimizer_uses_real_ordered_index_and_refreshes_rids(self):
        path = str(self.root / "data")
        storage = SequentialFile(path + ".main", path + ".aux", SCHEMA, "id", page_size=128)
        self.addCleanup(storage.close)
        for i in range(30):
            storage.insert({"id": i, "category": f"c{i % 3}", "value": float(i)})
        index = self.index(key_type="str", key_size=8, order=3, page_size=128)
        catalog = Catalog()
        binding = catalog.register_table("items", storage, {
            "category": IndexInfo("category_bplus", "category", index, ordered=True)
        })
        # Estadísticas simuladas de un archivo disperso: el recorrido B+ gana.
        binding.statistics = TableStats(30, 1000, {"category": 3})
        executor = SQLExecutor(catalog, BufferConfig(3, 2))
        with patch.object(storage, "scan", side_effect=AssertionError("Debe recorrer el B+")):
            ordered = list(executor.execute("SELECT category FROM items ORDER BY category DESC"))
            grouped = list(executor.execute("SELECT category, COUNT(*) AS n FROM items GROUP BY category"))
            filtered = list(executor.execute("SELECT id FROM items WHERE category='c1'"))
        self.assertEqual([r["category"] for r in ordered], ["c2"] * 10 + ["c1"] * 10 + ["c0"] * 10)
        self.assertEqual(grouped, [{"category": f"c{i}", "n": 10} for i in range(3)])
        self.assertEqual(sorted(r["id"] for r in filtered), list(range(1, 30, 3)))
        executor.execute("INSERT INTO items VALUES (-1, 'c1', 100)")
        executor.execute("DELETE FROM items WHERE id=3")
        for rid, row in storage.scan():
            self.assertIn(rid, index.search(row["category"]))
        self.assertEqual(sorted(r["id"] for r in executor.execute("SELECT id FROM items ORDER BY category")),
                         [-1] + [i for i in range(30) if i != 3])
