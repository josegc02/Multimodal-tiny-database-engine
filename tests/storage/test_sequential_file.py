import os
import tempfile
import unittest

from engine.storage.record import RID
from engine.storage.sequential_file import SequentialFile

SCHEMA = [
    ("id", "int"),
    ("name", "str", 20),
    ("price", "float"),
]


class TestSequentialFile(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.main_path = os.path.join(self.tmpdir, "test.seq.main")
        self.aux_path = os.path.join(self.tmpdir, "test.seq.aux")
        self.sf = SequentialFile(self.main_path, self.aux_path, SCHEMA, key_field="id", page_size=256)

    def tearDown(self):
        self.sf.close()

    def test_insert_sorted_within_page(self):
        self.sf.insert({"id": 30, "name": "C", "price": 3.0})
        self.sf.insert({"id": 10, "name": "A", "price": 1.0})
        self.sf.insert({"id": 20, "name": "B", "price": 2.0})

        page = self.sf._read_page_main(0)
        keys = [self.sf._record_key(data) for _, data in page.iter_active()]
        self.assertEqual(keys, [10, 20, 30], "Los registros en la página deben mantenerse ordenados por clave")

    def test_insert_overflow_to_aux(self):
        rids = []
        for i in range(10):
            rid = self.sf.insert({"id": i * 10, "name": f"item{i}", "price": float(i)})
            rids.append(rid)

        aux_rids = [r for r in rids if r.file == "aux"]
        self.assertGreater(len(aux_rids), 0, "Al llenarse main, los excedentes deben ir a aux")

    def test_delete_from_main(self):
        rid = self.sf.insert({"id": 1, "name": "Laptop", "price": 2500.0})
        self.assertEqual(rid.file, "main")

        ok = self.sf.delete(rid)
        self.assertTrue(ok)

        page = self.sf._read_page_main(rid.page_id)
        active_keys = [self.sf._record_key(data) for _, data in page.iter_active()]
        self.assertNotIn(1, active_keys)

    def test_delete_from_aux(self):
        rids = []
        for i in range(10):
            rid = self.sf.insert({"id": i * 10, "name": f"item{i}", "price": float(i)})
            rids.append(rid)

        aux_rid = next(r for r in rids if r.file == "aux")
        ok = self.sf.delete(aux_rid)
        self.assertTrue(ok)

        page = self.sf._read_page_aux(aux_rid.page_id)
        active_slots = [slot_id for slot_id, _ in page.iter_active()]
        self.assertNotIn(aux_rid.slot_id, active_slots)

    def test_delete_twice_returns_false(self):
        rid = self.sf.insert({"id": 42, "name": "Item", "price": 10.0})
        self.assertTrue(self.sf.delete(rid))
        self.assertFalse(self.sf.delete(rid))

    def test_delete_invalid_page_id_returns_false(self):
        fake_main_rid = RID(page_id=999, slot_id=0, file="main")
        fake_aux_rid = RID(page_id=999, slot_id=0, file="aux")
        self.assertFalse(self.sf.delete(fake_main_rid))
        self.assertFalse(self.sf.delete(fake_aux_rid))

    def test_delete_updates_page_bounds(self):
        self.sf.insert({"id": 10, "name": "A", "price": 1.0})
        self.sf.insert({"id": 20, "name": "B", "price": 2.0})
        self.sf.insert({"id": 30, "name": "C", "price": 3.0})

        self.assertEqual(self.sf._page_bounds[0], (10, 30))

        # Eliminar el menor (10)
        rid_min = RID(page_id=0, slot_id=0, file="main")
        self.assertTrue(self.sf.delete(rid_min))
        self.assertEqual(self.sf._page_bounds[0], (20, 30))

        # Eliminar el mayor (30)
        rid_max = RID(page_id=0, slot_id=2, file="main")
        self.assertTrue(self.sf.delete(rid_max))
        self.assertEqual(self.sf._page_bounds[0], (20, 20))

    def test_delete_all_records_leaves_bounds_none(self):
        rid = self.sf.insert({"id": 10, "name": "Unico", "price": 1.0})
        self.assertEqual(self.sf._page_bounds[0], (10, 10))

        self.assertTrue(self.sf.delete(rid))
        self.assertIsNone(self.sf._page_bounds[0])

    def test_needs_reorganization_empty(self):
        self.assertFalse(self.sf.needs_reorganization())

    def test_needs_reorganization_clean(self):
        self.sf.insert({"id": 1, "name": "A", "price": 1.0})
        self.sf.insert({"id": 2, "name": "B", "price": 2.0})
        self.assertFalse(self.sf.needs_reorganization())

    def test_needs_reorganization_by_deleted_records(self):
        rids = []
        for i in range(5):
            rids.append(self.sf.insert({"id": i, "name": f"item{i}", "price": float(i)}))

        # 0 borrados de 5 -> 0% <= 30%
        self.assertFalse(self.sf.needs_reorganization())

        # Borrar 2 registros -> 2 borrados / 5 total = 40% > 30%
        self.sf.delete(rids[0])
        self.sf.delete(rids[1])
        self.assertTrue(self.sf.needs_reorganization())

    def test_needs_reorganization_by_aux_overflow(self):
        # Insertar 10 registros: 6 van a main y 4 a aux (4/10 = 40% > 30%)
        for i in range(10):
            self.sf.insert({"id": i * 10, "name": f"item{i}", "price": float(i)})

        self.assertTrue(self.sf.needs_reorganization())

    def test_reorganize_empty(self):
        self.sf.reorganize()
        self.assertEqual(self.sf.num_pages_main, 0)
        self.assertEqual(self.sf.num_pages_aux, 0)

    def test_reorganize_consolidates_aux_and_purges_deleted(self):
        rids = []
        for i in range(10):
            rids.append(self.sf.insert({"id": i * 10, "name": f"item{i}", "price": float(i)}))

        self.sf.delete(rids[0])
        self.sf.delete(rids[7])
        self.assertTrue(self.sf.needs_reorganization())

        self.sf.reorganize()

        self.assertEqual(self.sf.num_pages_aux, 0)
        self.assertFalse(self.sf.needs_reorganization())

        keys = []
        for p_id in range(self.sf.num_pages_main):
            page = self.sf._read_page_main(p_id)
            for _, data in page.iter_active():
                rec = self.sf.schema.deserialize(data)
                keys.append(rec["id"])

        self.assertEqual(keys, sorted(keys))
        self.assertNotIn(0, keys)
        self.assertNotIn(70, keys)
        self.assertEqual(len(keys), 8)

    def test_get_record_main_and_aux(self):
        rid_main = self.sf.insert({"id": 10, "name": "MainRec", "price": 10.5})
        rec_main = self.sf.get(rid_main)
        self.assertIsNotNone(rec_main)
        self.assertEqual(rec_main["id"], 10)
        self.assertEqual(rec_main["name"], "MainRec")

        # Llenar página 0 de main para forzar a aux
        for i in range(1, 6):
            self.sf.insert({"id": 10 + i, "name": f"Main{i}", "price": float(i)})

        rid_aux = self.sf.insert({"id": 99, "name": "AuxRec", "price": 99.0})
        self.assertEqual(rid_aux.file, "aux")

        rec_aux = self.sf.get(rid_aux)
        self.assertIsNotNone(rec_aux)
        self.assertEqual(rec_aux["id"], 99)
        self.assertEqual(rec_aux["name"], "AuxRec")

    def test_get_invalid_or_deleted_returns_none(self):
        rid = self.sf.insert({"id": 10, "name": "A", "price": 1.0})
        self.assertIsNone(self.sf.get(RID(page_id=99, slot_id=0, file="main")))
        self.assertIsNone(self.sf.get(RID(page_id=0, slot_id=99, file="main")))
        self.assertIsNone(self.sf.get(RID(page_id=99, slot_id=0, file="aux")))

        self.sf.delete(rid)
        self.assertIsNone(self.sf.get(rid))

    def test_search_by_key_empty(self):
        self.assertEqual(self.sf.search_by_key(42), [])

    def test_search_by_key_in_main(self):
        for val in [30, 10, 20]:
            self.sf.insert({"id": val, "name": f"item{val}", "price": float(val)})

        results = self.sf.search_by_key(20)
        self.assertEqual(len(results), 1)
        rid, rec = results[0]
        self.assertEqual(rid.file, "main")
        self.assertEqual(rec["id"], 20)
        self.assertEqual(rec["name"], "item20")

    def test_search_by_key_in_aux(self):
        for i in range(6):
            self.sf.insert({"id": i * 10, "name": f"main{i}", "price": float(i)})

        rid_aux = self.sf.insert({"id": 99, "name": "overflow", "price": 99.0})
        self.assertEqual(rid_aux.file, "aux")

        results = self.sf.search_by_key(99)
        self.assertEqual(len(results), 1)
        rid, rec = results[0]
        self.assertEqual(rid.file, "aux")
        self.assertEqual(rec["id"], 99)

    def test_search_by_key_deleted_returns_empty(self):
        rid = self.sf.insert({"id": 50, "name": "ToDelete", "price": 50.0})
        self.assertEqual(len(self.sf.search_by_key(50)), 1)

        self.sf.delete(rid)
        self.assertEqual(self.sf.search_by_key(50), [])

    def test_search_by_key_nonexistent(self):
        self.sf.insert({"id": 10, "name": "A", "price": 1.0})
        self.sf.insert({"id": 20, "name": "B", "price": 2.0})
        self.assertEqual(self.sf.search_by_key(999), [])


if __name__ == "__main__":
    unittest.main()


