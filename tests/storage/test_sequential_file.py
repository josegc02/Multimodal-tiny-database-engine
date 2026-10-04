import os
import random
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
        # Mecánica manual: sin reorganización automática los RIDs del test no cambian.
        self.sf = SequentialFile(self.main_path, self.aux_path, SCHEMA, key_field="id",
                                 page_size=256, auto_reorganize=False)

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

    def test_order_preserved_random_insertions(self):
        keys = list(range(1, 21))
        shuffled = keys.copy()
        random.Random(42).shuffle(shuffled)

        main_p = os.path.join(self.tmpdir, "random.main")
        aux_p = os.path.join(self.tmpdir, "random.aux")
        sf_large = SequentialFile(main_p, aux_p, SCHEMA, key_field="id", page_size=2048)
        try:
            for k in shuffled:
                sf_large.insert({"id": k, "name": f"item{k}", "price": float(k)})

            collected = []
            for p_id in range(sf_large.num_pages_main):
                page = sf_large._read_page_main(p_id)
                for _, data in page.iter_active():
                    collected.append(sf_large._record_key(data))

            self.assertEqual(collected, sorted(keys))
        finally:
            sf_large.close()

    def test_reorganize_empty(self):
        self.sf.reorganize()
        self.assertEqual(self.sf.num_pages_main, 0)
        self.assertEqual(self.sf.num_pages_aux, 0)

    def test_reorganize_consolidates_aux_and_purges_deleted(self):
        keys_inserted = list(range(10, 130, 10))
        rids = {}
        for k in keys_inserted:
            rids[k] = self.sf.insert({"id": k, "name": f"item{k}", "price": float(k)})

        self.assertTrue(any(r.file == "aux" for r in rids.values()))

        deleted_keys = [10, 30, 80, 100]
        for dk in deleted_keys:
            self.assertTrue(self.sf.delete(rids[dk]))

        self.assertTrue(self.sf.needs_reorganization())

        self.sf.reorganize(fill_factor=0.9)

        # a) aux queda vacío
        self.assertEqual(self.sf.num_pages_aux, 0)

        # b) registros activos siguen encontrables tras reorganizar
        active_keys = [k for k in keys_inserted if k not in deleted_keys]
        for ak in active_keys:
            res = self.sf.search_by_key(ak)
            self.assertEqual(len(res), 1)
            self.assertEqual(res[0][0].file, "main")
            self.assertEqual(res[0][1]["id"], ak)

        # c) registros eliminados no aparecen tras reorganizar
        for dk in deleted_keys:
            self.assertEqual(self.sf.search_by_key(dk), [])

        # d) needs_reorganization vuelve a ser False
        self.assertFalse(self.sf.needs_reorganization())

        # e) main sigue ordenado globalmente
        global_keys = []
        for p_id in range(self.sf.num_pages_main):
            page = self.sf._read_page_main(p_id)
            for _, data in page.iter_active():
                global_keys.append(self.sf._record_key(data))

        self.assertEqual(global_keys, active_keys)
        self.assertEqual(global_keys, sorted(global_keys))

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

    def test_aux_key_index_survives_reopen_delete_and_duplicates(self):
        for i in range(6):
            self.sf.insert({"id": i * 10, "name": f"main{i}", "price": 0.0})
        for key in (99, 77, 77):
            self.assertEqual(self.sf.insert({"id": key, "name": "aux", "price": 1.0}).file, "aux")
        self.sf.close()
        self.sf = SequentialFile(self.main_path, self.aux_path, SCHEMA, key_field="id",
                                 page_size=256, auto_reorganize=False)
        self.assertEqual(len(self.sf.search_by_key(77)), 2)
        rid = self.sf.search_by_key(99)[0][0]
        self.assertTrue(self.sf.delete(rid))
        self.assertEqual(self.sf.search_by_key(99), [])
        self.assertEqual(len(self.sf.search_by_key(77)), 2)
        self.sf.reorganize()
        self.assertEqual([r["id"] for _, r in self.sf.search_by_key(77)], [77, 77])
        self.assertEqual(self.sf.search_by_key(77)[0][0].file, "main")

    def test_search_by_key_deleted_returns_empty(self):
        rid = self.sf.insert({"id": 50, "name": "ToDelete", "price": 50.0})
        self.assertEqual(len(self.sf.search_by_key(50)), 1)

        self.sf.delete(rid)
        self.assertEqual(self.sf.search_by_key(50), [])

    def test_search_by_key_nonexistent(self):
        self.sf.insert({"id": 10, "name": "A", "price": 1.0})
        self.sf.insert({"id": 20, "name": "B", "price": 2.0})
        self.assertEqual(self.sf.search_by_key(999), [])


class TestSequentialFileAutoReorganize(unittest.TestCase):
    """Comportamiento por defecto: main crece y aux queda acotado."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.paths = (os.path.join(self.tmpdir, "auto.main"), os.path.join(self.tmpdir, "auto.aux"))
        self.sf = SequentialFile(*self.paths, SCHEMA, key_field="id", page_size=256)

    def tearDown(self):
        self.sf.close()

    def _insert_shuffled(self, n, seed=7):
        keys = list(range(n))
        random.Random(seed).shuffle(keys)
        for k in keys:
            self.sf.insert({"id": k, "name": f"item{k}", "price": float(k)})
        return keys

    def _main_keys(self):
        return [key for _, key, _ in self.sf._iter_main_all()]

    def test_random_inserts_grow_main_and_bound_aux(self):
        self._insert_shuffled(500)
        self.assertGreater(self.sf.num_pages_main, 50)
        self.assertLessEqual(self.sf.num_pages_aux, self.sf.aux_page_limit + 1)
        self.assertGreater(self.sf.reorganizations, 0)
        self.assertEqual(self._main_keys(), sorted(self._main_keys()))
        self.assertEqual(sorted(r["id"] for _, r in self.sf.scan()), list(range(500)))

    def test_search_finds_every_key_main_or_aux(self):
        self._insert_shuffled(300)
        for k in range(300):
            result = self.sf.search_by_key(k)
            self.assertEqual([r["id"] for _, r in result], [k])
            self.assertEqual(self.sf.get(result[0][0])["id"], k)
        self.assertEqual(self.sf.search_by_key(1000), [])

    def test_returned_rid_is_valid_after_auto_reorganization(self):
        for k in random.Random(3).sample(range(1000), 200):
            rid = self.sf.insert({"id": k, "name": "x", "price": 0.0})
            self.assertEqual(self.sf.get(rid)["id"], k)

    def test_range_search_merges_main_and_aux(self):
        self._insert_shuffled(300)
        self.assertEqual([r["id"] for _, r in self.sf.range_search(40, 120)], list(range(40, 121)))
        self.assertEqual(self.sf.range_search(5, 4), [])

    def test_range_search_open_and_exclusive_bounds(self):
        self._insert_shuffled(100)
        ids = lambda **kw: [r["id"] for _, r in self.sf.range_search(**kw)]
        self.assertEqual(ids(), list(range(100)))
        self.assertEqual(ids(lower=95), list(range(95, 100)))
        self.assertEqual(ids(upper=3), [0, 1, 2, 3])
        self.assertEqual(ids(lower=10, upper=14, include_lower=False, include_upper=False), [11, 12, 13])

    def test_key_index_view_uses_current_rids(self):
        index = self.sf.primary_index_info("t_key").index
        self._insert_shuffled(200)
        self.sf.reorganize()
        self.assertEqual([self.sf.get(rid)["id"] for rid in index.search(150)], [150])
        self.assertEqual([self.sf.get(rid)["id"] for rid in index.range_search(10, 12)], [10, 11, 12])
        self.assertEqual([self.sf.get(rid)["id"] for rid in index.iter_ordered(reverse=True)][:2], [199, 198])

    def test_duplicate_keys_are_all_returned(self):
        for i in range(20):
            self.sf.insert({"id": 7, "name": f"dup{i}", "price": float(i)})
            self.sf.insert({"id": i * 3, "name": "other", "price": 0.0})
        self.assertEqual(len(self.sf.search_by_key(7)), 20)

    def test_routing_survives_empty_middle_page(self):
        self._insert_shuffled(200)
        self.sf.reorganize()
        middle = self.sf.num_pages_main // 2
        page = self.sf._read_page_main(middle)
        for slot_id, _ in list(page.iter_active()):
            self.assertTrue(self.sf.delete(RID(middle, slot_id, "main")))
        self.assertIsNone(self.sf._page_bounds[middle])
        self.sf.auto_reorganize = False
        for k in range(1000, 1010):
            self.sf.insert({"id": k, "name": "tail", "price": 0.0})
        self.assertEqual(self._main_keys(), sorted(self._main_keys()))
        for k in range(1000, 1010):
            self.assertEqual(len(self.sf.search_by_key(k)), 1)

    def test_delete_threshold_triggers_on_next_insert_and_counters_persist(self):
        self._insert_shuffled(200)
        self.sf.reorganize()
        victims = [rid for rid, r in self.sf.scan() if r["id"] % 3 == 0]
        for rid in victims:
            self.assertTrue(self.sf.delete(rid))
        self.assertTrue(self.sf.needs_reorganization())
        self.sf.close()
        self.sf = SequentialFile(*self.paths, SCHEMA, key_field="id", page_size=256)
        self.assertTrue(self.sf.needs_reorganization())
        before = self.sf.reorganizations
        self.sf.insert({"id": 999, "name": "new", "price": 0.0})
        self.assertEqual(self.sf.reorganizations, before + 1)
        self.assertEqual(sorted(r["id"] for _, r in self.sf.scan()),
                         sorted([k for k in range(200) if k % 3] + [999]))


if __name__ == "__main__":
    unittest.main()


