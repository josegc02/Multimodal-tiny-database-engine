import os
import tempfile
import unittest

from engine.storage.heap_file import HeapFile
from engine.storage.record import Schema


class TestSchemaSerialization(unittest.TestCase):
    def setUp(self):
        self.schema = Schema([("id", "int"), ("nombre", "str", 5), ("precio", "float")])

    def roundtrip(self, record):
        return self.schema.deserialize(self.schema.serialize(record))

    def test_long_multibyte_strings_are_cut_at_a_character_boundary(self):
        # 'añoññ' ocupa 8 bytes; cortar en 5 partiría la segunda 'ñ'.
        self.assertEqual(self.roundtrip({"id": 1, "nombre": "añoññ", "precio": 1.0})["nombre"], "año")
        self.assertEqual(self.roundtrip({"id": 2, "nombre": "ñññ", "precio": 1.0})["nombre"], "ññ")
        self.assertEqual(self.roundtrip({"id": 3, "nombre": "€€", "precio": 1.0})["nombre"], "€")
        self.assertEqual(self.roundtrip({"id": 4, "nombre": "abcdefg", "precio": 1.0})["nombre"], "abcde")

    def test_strings_that_fit_are_preserved(self):
        self.assertEqual(self.roundtrip({"id": 1, "nombre": "José", "precio": 2.5}),
                         {"id": 1, "nombre": "José", "precio": 2.5})

    def test_missing_fields_are_rejected_instead_of_storing_none(self):
        for record in ({"id": 1, "precio": 1.0}, {"id": None, "nombre": "x", "precio": 1.0}):
            with self.assertRaises(ValueError):
                self.schema.serialize(record)

    def test_heap_scan_survives_truncated_multibyte_values(self):
        path = os.path.join(tempfile.mkdtemp(), "t.heap")
        with HeapFile(path, [("id", "int"), ("nombre", "str", 5), ("precio", "float")]) as heap:
            heap.insert({"id": 1, "nombre": "Muñoz", "precio": 1.0})
            heap.insert({"id": 2, "nombre": "Peñaflor", "precio": 2.0})
            self.assertEqual([r["nombre"] for _, r in heap.scan()], ["Muño", "Peña"])


if __name__ == "__main__":
    unittest.main()
