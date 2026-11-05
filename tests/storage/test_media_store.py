import os
import tempfile
import unittest

import numpy as np

from engine.storage.heap_file import HeapFile
from engine.storage.media_store import MediaStore


class FakeExtractor:
    """Vector conocido por ruta; cuenta las extracciones."""

    def __init__(self, vectors):
        self.vectors = vectors
        self.calls = []

    def __call__(self, kind, path):
        self.calls.append((kind, path))
        if path not in self.vectors:
            raise FileNotFoundError(path)
        return np.asarray(self.vectors[path], dtype=np.float32)


class MediaStoreTestCase(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = os.path.join(temp.name, "tabla.media")
        self.extract = FakeExtractor({"a.jpg": [1, 2, 3], "b.jpg": [0.5, 0, -1], "c.wav": [9, 8]})

    def open(self):
        store = MediaStore(self.path, self.extract)
        self.addCleanup(store.close)
        return store


class TestMediaStore(MediaStoreTestCase):
    def test_guarda_ruta_y_vector(self):
        store = self.open()
        reference = store.put("image", "a.jpg")
        self.assertEqual(store.get(*reference), "a.jpg")
        np.testing.assert_array_equal(store.vector("image", "a.jpg"), [1, 2, 3])
        self.assertEqual(store.vector("image", "a.jpg").dtype, np.float64)

    def test_extrae_una_sola_vez_por_ruta(self):
        store = self.open()
        self.assertEqual(store.put("image", "a.jpg"), store.put("image", "a.jpg"))
        self.assertEqual(self.extract.calls, [("image", "a.jpg")])

    def test_el_tipo_forma_parte_de_la_clave(self):
        store = self.open()
        self.extract.vectors["x"] = [1.0]
        self.assertNotEqual(store.put("image", "x"), store.put("audio", "x"))

    def test_persiste_al_reabrir_sin_volver_a_extraer(self):
        store = self.open()
        first = store.put("image", "b.jpg")
        audio = store.put("audio", "c.wav")
        store.close()
        reopened = self.open()
        self.assertEqual(reopened.put("image", "b.jpg"), first)
        self.assertEqual(reopened.get(*audio), "c.wav")
        np.testing.assert_array_equal(reopened.vector("audio", "c.wav"), [9, 8])
        self.assertEqual(len(self.extract.calls), 2)

    def test_archivo_inexistente_explica_el_error(self):
        store = self.open()
        with self.assertRaisesRegex(ValueError, "no_existe.jpg"):
            store.put("image", "no_existe.jpg")
        self.assertFalse(os.path.exists(self.path))

    def test_ruta_desconocida_y_tipo_invalido(self):
        store = self.open()
        with self.assertRaises(KeyError):
            store.vector("image", "a.jpg")
        with self.assertRaises(ValueError):
            store.put("video", "a.jpg")

    def test_archivo_truncado(self):
        store = self.open()
        store.put("image", "a.jpg")
        store.close()
        with open(self.path, "r+b") as fh:
            fh.truncate(os.path.getsize(self.path) - 1)
        with self.assertRaises(ValueError):
            MediaStore(self.path, self.extract)

    def test_tabla_con_columnas_image_y_audio(self):
        store = self.open()
        heap = HeapFile(self.path + ".db", [("id", "int"), ("foto", "image", store), ("sonido", "audio", store)])
        self.addCleanup(heap.close)
        schema = heap.schema
        rid = heap.insert({"id": 1, "foto": "a.jpg", "sonido": "c.wav"})
        self.assertEqual(heap.get(rid), {"id": 1, "foto": "a.jpg", "sonido": "c.wav"})
        np.testing.assert_array_equal(schema.vector("sonido", "c.wav"), [9, 8])
        with self.assertRaises(ValueError):
            heap.insert({"id": 2, "foto": "", "sonido": "c.wav"})


if __name__ == "__main__":
    unittest.main()
