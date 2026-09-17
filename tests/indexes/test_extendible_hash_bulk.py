import os
import tempfile
import unittest

from engine.indexes import ExtendibleHash
from engine.storage.heap_file import HeapFile
from engine.storage.record import RID
from engine.storage.sequential_file import SequentialFile

SCHEMA = [("id", "int"), ("name", "str", 12), ("price", "float")]


class TestExtendibleHashBulk(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def heap(self):
        storage = HeapFile(os.path.join(self.tmp.name, "data.heap"), SCHEMA, page_size=128)
        self.addCleanup(storage.close)
        return storage

    def sequential(self):
        storage = SequentialFile(
            os.path.join(self.tmp.name, "data.main"),
            os.path.join(self.tmp.name, "data.aux"), SCHEMA, "id", page_size=128,
        )
        self.addCleanup(storage.close)
        return storage

    def assert_matches_scan(self, index, storage, field):
        expected = {}
        for rid, record in storage.scan():
            expected.setdefault(record[field], []).append(rid)
        self.assertEqual(len(index), sum(map(len, expected.values())))
        for key, rids in expected.items():
            self.assertCountEqual(index.search(key), rids)
            for rid in index.search(key):
                self.assertEqual(storage.get(rid)[field], key)

    def test_bulk_iterable_append_replace_and_duplicates(self):
        index = ExtendibleHash(bucket_capacity=2)
        self.assertEqual(index.bulk_load((i, RID(i, 0)) for i in range(100)), 100)
        self.assertEqual(index.bulk_load([(1, RID(1, 0)), (1, RID(1, 1))]), 1)
        self.assertEqual(len(index), 101)
        self.assertEqual(index.bulk_load([(8, RID(2, 0))], replace=True), 1)
        self.assertEqual(index.search(1), [])
        self.assertEqual(index.search(8), [RID(2, 0)])
        self.assertEqual(index.bulk_load([], replace=True), 0)
        self.assertEqual(len(index), 0)

    def test_failed_replacement_preserves_previous_index(self):
        index = ExtendibleHash()
        index.insert(99, RID(0, 0))

        def failing_source():
            yield 1, RID(1, 0)
            raise OSError("lectura interrumpida")

        with self.assertRaises(OSError):
            index.bulk_load(failing_source(), replace=True)
        self.assertEqual(index.search(99), [RID(0, 0)])
        self.assertEqual(index.search(1), [])
        with self.assertRaises(TypeError):
            index.bulk_load([(2, RID(2, 0)), (None, RID(3, 0))], replace=True)
        self.assertEqual(len(index), 1)

    def test_heap_existing_data_deletes_and_reused_slots(self):
        storage = self.heap()
        for i in range(30):
            storage.insert({"id": i, "name": f"grupo{i % 3}", "price": i / 2})
        deleted = storage.search_by_key("id", 5)[0][0]
        storage.delete(deleted)
        index = ExtendibleHash(bucket_capacity=2)
        self.assertEqual(index.bulk_load_from_storage(storage, "id"), 29)
        self.assertEqual(index.search(5), [])
        self.assert_matches_scan(index, storage, "id")
        old = index.search(7)[0]
        storage.delete(old)
        storage.insert({"id": 77, "name": "nuevo", "price": 8.5})
        self.assertEqual(index.bulk_load_from_storage(storage, "id"), 29)
        self.assertEqual(index.search(7), [])
        self.assert_matches_scan(index, storage, "id")

    def test_heap_secondary_field_duplicates_and_serialized_values(self):
        storage = self.heap()
        for i in range(20):
            storage.insert({"id": i, "name": "abcdefghijkl-truncado", "price": i % 2})
        index = ExtendibleHash(bucket_capacity=2)
        self.assertEqual(index.bulk_load_from_storage(storage, "name"), 20)
        self.assertEqual(len(index.search("abcdefghijkl")), 20)
        self.assert_matches_scan(index, storage, "name")
        index.bulk_load_from_storage(storage, "price")
        self.assert_matches_scan(index, storage, "price")

    def test_sequential_current_rids_main_aux_and_reorganization(self):
        storage = self.sequential()
        for i in [30, 10, 20, 50, 40, 70, 60, 90, 80]:
            storage.insert({"id": i, "name": f"grupo{i % 3}", "price": float(i)})
        scanned = list(storage.scan())
        self.assertEqual({rid.file for rid, _ in scanned}, {"main", "aux"})
        for file in ["main", "aux"]:
            rid = next(rid for rid, _ in scanned if rid.file == file)
            self.assertTrue(storage.delete(rid))
        index = ExtendibleHash(bucket_capacity=2)
        self.assertEqual(index.bulk_load_from_storage(storage, "id"), 7)
        self.assert_matches_scan(index, storage, "id")
        storage.reorganize(fill_factor=0.5)
        self.assertEqual(index.bulk_load_from_storage(storage, "id"), 7)
        self.assertTrue(all(rid.file == "main" for rid, _ in storage.scan()))
        self.assert_matches_scan(index, storage, "id")
        # Insertar antes del primer slot desplaza los RIDs de esa página.
        storage.insert({"id": -1, "name": "nuevo", "price": 1.0})
        index.bulk_load_from_storage(storage, "id")
        self.assert_matches_scan(index, storage, "id")

    def test_empty_storage_and_unknown_field(self):
        index = ExtendibleHash()
        index.insert(9, RID(0, 0))
        storage = self.heap()
        with self.assertRaises(ValueError):
            index.bulk_load_from_storage(storage, "missing")
        self.assertEqual(index.search(9), [RID(0, 0)])
        self.assertEqual(index.bulk_load_from_storage(storage, "id"), 0)
        self.assertEqual(len(index), 0)
        self.assertEqual(index.bulk_load_from_storage(self.sequential(), "id"), 0)

    def test_storage_append_is_idempotent(self):
        storage = self.heap()
        storage.insert({"id": 1, "name": "uno", "price": 1.0})
        index = ExtendibleHash()
        self.assertEqual(index.bulk_load_from_storage(storage, "id", replace=False), 1)
        self.assertEqual(index.bulk_load_from_storage(storage, "id", replace=False), 0)
        storage.insert({"id": 2, "name": "dos", "price": 2.0})
        self.assertEqual(index.bulk_load_from_storage(storage, "id", replace=False), 1)
        self.assert_matches_scan(index, storage, "id")


if __name__ == "__main__":
    unittest.main()
