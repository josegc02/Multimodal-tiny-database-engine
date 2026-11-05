import os
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from frontend.motor import Motor

# Vectores conocidos por ruta: el extractor real (SIFT/MFCC) se prueba en test_multimedia_e2e.
VECTORS = {
    "img/gato.jpg": [1.0, 0.0, 0.0],
    "img/gato2.jpg": [0.9, 0.1, 0.0],
    "img/perro.jpg": [0.0, 1.0, 0.0],
    "img/perro2.jpg": [0.1, 0.9, 0.1],
    "img/ave.jpg": [0.0, 0.0, 1.0],
    "img/pez.jpg": [0.3, 0.3, 0.9],
    "img/consulta.jpg": [0.95, 0.05, 0.0],
    "aud/a.wav": [1.0, 2.0],
    "aud/b.wav": [2.0, 1.0],
}


def fake_extract(kind, path):
    if path not in VECTORS:
        raise FileNotFoundError(f"Archivo no encontrado: {path}")
    return np.asarray(VECTORS[path], dtype=np.float32)


class MultimediaSQLTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        for target, value in (("frontend.motor.DEMO_DIR", self.temp_dir.name),
                              ("engine.storage.media_store.extract_features", fake_extract)):
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.motor = Motor()
        self.addCleanup(self.motor.cerrar)

    def execute(self, sql):
        result = self.motor.ejecutar(sql)
        self.assertFalse(result.tiene_error, result.error)
        return result

    def fails(self, sql):
        result = self.motor.ejecutar(sql)
        self.assertTrue(result.tiene_error, f"Se esperaba un error: {sql}")
        return result.error


class TestMediaColumns(MultimediaSQLTestCase):
    def test_insert_stores_the_path_and_extracts_the_vector(self):
        self.execute("CREATE TABLE fotos (id INT PRIMARY KEY, nombre VARCHAR(20), foto IMAGE, sonido AUDIO)")
        self.execute("INSERT INTO fotos VALUES (1, 'gato', 'img/gato.jpg', 'aud/a.wav'), "
                     "(2, 'perro', 'img/perro.jpg', 'aud/b.wav')")
        self.assertEqual(self.execute("SELECT id, foto, sonido FROM fotos WHERE foto = 'img/perro.jpg'").filas,
                         [(2, "img/perro.jpg", "aud/b.wav")])
        schema = self.motor.catalog.table("fotos").storage.schema
        np.testing.assert_allclose(schema.vector("foto", "img/gato.jpg"), VECTORS["img/gato.jpg"])
        np.testing.assert_allclose(schema.vector("sonido", "aud/b.wav"), VECTORS["aud/b.wav"])
        self.assertTrue(os.path.exists(os.path.join(self.temp_dir.name, "fotos.media")))

    def test_missing_file_rejects_the_insert(self):
        self.execute("CREATE TABLE fotos (id INT, foto IMAGE)")
        self.assertIn("no_existe.jpg", self.fails("INSERT INTO fotos VALUES (1, 'no_existe.jpg')"))
        self.assertEqual(self.execute("SELECT COUNT(*) FROM fotos").filas, [(0,)])

    def test_every_storage_keeps_media_columns(self):
        for method in ("HEAP", "SEQUENTIAL", "BTREE"):
            with self.subTest(method=method):
                table = f"t_{method.lower()}"
                self.execute(f"CREATE TABLE {table} (id INT PRIMARY KEY, foto IMAGE) USING {method}")
                self.execute(f"INSERT INTO {table} VALUES (2, 'img/ave.jpg'), (1, 'img/gato.jpg')")
                self.assertEqual(self.execute(f"SELECT id, foto FROM {table} ORDER BY id").filas,
                                 [(1, "img/gato.jpg"), (2, "img/ave.jpg")])

    def test_image_and_audio_are_not_reserved_words(self):
        self.execute("CREATE TABLE medios (image IMAGE, audio AUDIO, id INT)")
        self.execute("INSERT INTO medios VALUES ('img/pez.jpg', 'aud/a.wav', 1)")
        self.assertEqual(self.execute("SELECT image, audio FROM medios").filas, [("img/pez.jpg", "aud/a.wav")])

    def test_media_columns_cannot_be_keys(self):
        self.execute("CREATE TABLE padre (id INT PRIMARY KEY)")
        for sql in ("CREATE TABLE a (foto IMAGE PRIMARY KEY)",
                    "CREATE TABLE b (sonido AUDIO, id INT) USING SEQUENTIAL",
                    "CREATE TABLE c (id INT, foto IMAGE REFERENCES padre)",
                    "CREATE TABLE d (foto IMAGE(10))"):
            with self.subTest(sql=sql):
                self.fails(sql)

    def test_media_columns_require_a_path(self):
        self.execute("CREATE TABLE fotos (id INT, foto IMAGE)")
        for value in ("1", "''", "POINT(1, 2)"):
            with self.subTest(value=value):
                self.fails(f"INSERT INTO fotos VALUES (1, {value})")

    def test_copy_loads_media_columns(self):
        path = os.path.join(self.temp_dir.name, "fotos.csv")
        with open(path, "w", encoding="utf-8") as stream:
            stream.write("id,foto\n1, img/gato.jpg\n2,img/perro.jpg\n")
        self.execute("CREATE TABLE fotos (id INT, foto IMAGE)")
        self.execute(f"COPY fotos FROM '{path}' WITH (FORMAT csv, HEADER true)")
        self.assertEqual(self.execute("SELECT foto FROM fotos ORDER BY id").filas,
                         [("img/gato.jpg",), ("img/perro.jpg",)])

    def test_media_columns_only_admit_vector_indexes(self):
        self.execute("CREATE TABLE fotos (id INT, foto IMAGE)")
        for method in ("HASH", "BTREE", "SPIMI"):
            with self.subTest(method=method):
                self.fails(f"CREATE INDEX i ON fotos (foto) USING {method}")


if __name__ == "__main__":
    unittest.main()
