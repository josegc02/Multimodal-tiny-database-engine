import os
import tempfile
import unittest

from engine.storage.heap_file import HeapFile
from engine.storage.record import RID

SCHEMA = [
    ("id", "int"),
    ("name", "str", 20),
    ("price", "float"),
]


class TestHeapFile(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.filepath = os.path.join(self.tmpdir, "test.heap")
        self.hf = HeapFile(self.filepath, SCHEMA, page_size=256)

    def tearDown(self):
        self.hf.close()

    def test_insert_and_get(self):
        rid = self.hf.insert({"id": 1, "name": "Laptop", "price": 2500.0})
        record = self.hf.get(rid)
        self.assertIsNotNone(record)
        self.assertEqual(record["id"], 1)
        self.assertEqual(record["name"], "Laptop")
        self.assertEqual(record["price"], 2500.0)

    def test_insertion_order_preserved_within_page(self):
        rids = []
        for i in range(3):
            rid = self.hf.insert({"id": i, "name": f"item{i}", "price": float(i)})
            rids.append(rid)

        scanned_ids = [record["id"] for _, record in self.hf.scan()]
        self.assertEqual(scanned_ids, [0, 1, 2], "El orden de llegada debe respetarse")

    def test_delete_marks_logically_not_physically(self):
        rid = self.hf.insert({"id": 1, "name": "A", "price": 1.0})
        ok = self.hf.delete(rid)
        self.assertTrue(ok)

        self.assertIsNone(self.hf.get(rid))
        self.assertEqual(list(self.hf.scan()), [])
        self.assertGreater(os.path.getsize(self.filepath), 0)

    def test_delete_nonexistent_returns_false(self):
        fake_rid = RID(page_id=0, slot_id=99)
        self.assertFalse(self.hf.delete(fake_rid))

    def test_reuse_deleted_slot_space(self):
        rid1 = self.hf.insert({"id": 1, "name": "A", "price": 1.0})
        self.hf.delete(rid1)

        rid2 = self.hf.insert({"id": 2, "name": "B", "price": 2.0})

        self.assertEqual(rid1.page_id, rid2.page_id)
        self.assertEqual(rid1.slot_id, rid2.slot_id)

        record = self.hf.get(rid2)
        self.assertEqual(record["id"], 2)

    def test_stats_reflect_active_and_deleted(self):
        rid1 = self.hf.insert({"id": 1, "name": "A", "price": 1.0})
        self.hf.insert({"id": 2, "name": "B", "price": 2.0})
        self.hf.delete(rid1)

        stats = self.hf.stats()
        self.assertEqual(stats["active_records"], 1)
        self.assertEqual(stats["deleted_slots"], 1)

    def test_search_by_key(self):
        self.hf.insert({"id": 1, "name": "Mouse", "price": 20.0})
        self.hf.insert({"id": 2, "name": "Teclado", "price": 35.0})
        self.hf.insert({"id": 3, "name": "Mouse", "price": 22.5})

        results = self.hf.search_by_key("name", "Mouse")
        self.assertEqual(len(results), 2)
        ids_found = sorted(r["id"] for _, r in results)
        self.assertEqual(ids_found, [1, 3])

    def test_search_by_key_no_match(self):
        self.hf.insert({"id": 1, "name": "Mouse", "price": 20.0})
        results = self.hf.search_by_key("name", "NoExiste")
        self.assertEqual(results, [])

    def test_overflow_creates_new_page(self):
        for i in range(20):
            self.hf.insert({"id": i, "name": f"producto{i}", "price": float(i)})

        self.assertGreater(self.hf.num_pages, 1, "Debió crear más de una página")
        scanned = list(self.hf.scan())
        self.assertEqual(len(scanned), 20)

    def test_reopen_file_preserves_data(self):
        rid = self.hf.insert({"id": 42, "name": "Persistente", "price": 99.9})
        self.hf.close()

        hf2 = HeapFile(self.filepath, SCHEMA, page_size=256)
        record = hf2.get(rid)
        self.assertIsNotNone(record)
        self.assertEqual(record["id"], 42)
        hf2.close()


if __name__ == "__main__":
    unittest.main()
