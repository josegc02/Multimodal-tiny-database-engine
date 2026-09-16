import os
import tempfile
import unittest

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
        # Insertar desordenados: 30, 10, 20
        self.sf.insert({"id": 30, "name": "C", "price": 3.0})
        self.sf.insert({"id": 10, "name": "A", "price": 1.0})
        self.sf.insert({"id": 20, "name": "B", "price": 2.0})

        page = self.sf._read_page_main(0)
        keys = [self.sf._record_key(data) for _, data in page.iter_active()]
        self.assertEqual(keys, [10, 20, 30], "Los registros en la página deben mantenerse ordenados por clave")

    def test_insert_overflow_to_aux(self):
        # Con page_size=256 y record ~36B, caben aprox 5 registros por página.
        # Insertamos 10 registros para forzar desbordamiento al área auxiliar.
        rids = []
        for i in range(10):
            rid = self.sf.insert({"id": i * 10, "name": f"item{i}", "price": float(i)})
            rids.append(rid)

        aux_rids = [r for r in rids if r.file == "aux"]
        self.assertGreater(len(aux_rids), 0, "Al llenarse main, los excedentes deben ir a aux")


if __name__ == "__main__":
    unittest.main()
