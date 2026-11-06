"""SQL multimedia con ExtractFeatures real: Bag of Words sobre SIFT (IMAGE) y MFCC (AUDIO)."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

try:
    import cv2
    import soundfile
except ImportError:  # pragma: no cover - dependencia opcional del entorno
    cv2 = soundfile = None

from engine.features.registry import extract_features
from frontend.motor import Motor


@unittest.skipIf(cv2 is None or soundfile is None, "requiere opencv-python y soundfile")
class TestRealExtractors(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        patcher = patch("frontend.motor.DEMO_DIR", self.temp_dir.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.motor = Motor()
        self.addCleanup(self.motor.cerrar)

    def path(self, name):
        return os.path.join(self.temp_dir.name, name).replace("\\", "/")

    def execute(self, sql):
        result = self.motor.ejecutar(sql)
        self.assertFalse(result.tiene_error, result.error)
        return result.filas

    def write_images(self):
        rng = np.random.default_rng(3)
        for i in range(5):
            image = rng.integers(0, 255, (160, 160), dtype=np.uint8)
            cv2.imwrite(self.path(f"img{i}.png"), image)
            if i == 2:
                # La consulta es la imagen 2 con un poco de ruido: SIFT debe reconocerla.
                noisy = np.clip(image.astype(int) + rng.integers(-6, 7, image.shape), 0, 255).astype(np.uint8)
                cv2.imwrite(self.path("consulta.png"), noisy)

    def test_image_search_with_sift(self):
        self.write_images()
        self.execute("CREATE TABLE imagenes (id INT PRIMARY KEY, foto IMAGE)")
        values = ", ".join(f"({i}, '{self.path(f'img{i}.png')}')" for i in range(5))
        self.execute(f"INSERT INTO imagenes VALUES {values}")
        self.execute("CREATE INDEX imagenes_foto ON imagenes (foto) USING HNSW WITH (METRIC = cosine)")
        schema = self.motor.catalog.table("imagenes").storage.schema
        self.assertEqual(schema.vector("foto", self.path("img0.png")).shape, (256,))
        rows = self.execute(f"SELECT id, SIMILARITY_SCORE() FROM imagenes "
                            f"WHERE SIMILAR_TO('{self.path('consulta.png')}', k=3) USING HNSW WITH METRIC=cosine")
        self.assertEqual(rows[0][0], 2)
        self.assertEqual(len(rows), 3)

    def test_audio_search_with_mfcc(self):
        rate = 22050
        times = np.arange(rate) / rate
        for i, frequency in enumerate((220, 440, 880, 1760)):
            soundfile.write(self.path(f"tono{i}.wav"), 0.5 * np.sin(2 * np.pi * frequency * times), rate)
        soundfile.write(self.path("consulta.wav"), 0.5 * np.sin(2 * np.pi * 900 * times), rate)
        self.execute("CREATE TABLE canciones (id INT, audio AUDIO)")
        self.execute("CREATE INDEX canciones_audio ON canciones (audio) USING IVF")
        values = ", ".join(f"({i}, '{self.path(f'tono{i}.wav')}')" for i in range(4))
        self.execute(f"INSERT INTO canciones VALUES {values}")
        rows = self.execute(f"SELECT id FROM canciones WHERE SIMILAR_TO('{self.path('consulta.wav')}', k=1) "
                            "USING IVF WITH METRIC=euclidean")
        self.assertEqual(rows, [(2,)])
        schema = self.motor.catalog.table("canciones").storage.schema
        self.assertEqual(schema.vector("audio", self.path("tono0.wav")).shape, (256,))

    def test_vectors_are_bag_of_words_histograms(self):
        self.write_images()
        vector = extract_features("image", self.path("img0.png"))
        self.assertEqual(vector.shape, (256,))
        self.assertAlmostEqual(float(np.linalg.norm(vector)), 1.0, places=5)
        self.assertTrue(np.all(vector >= 0))
        # Un histograma: la mayoría de las palabras no aparecen en una sola imagen.
        self.assertLess(np.count_nonzero(vector), 256)

    def test_image_without_keypoints_is_the_zero_vector(self):
        self.write_images()
        cv2.imwrite(self.path("gris.png"), np.full((160, 160), 128, dtype=np.uint8))
        self.assertFalse(extract_features("image", self.path("gris.png")).any())
        self.execute("CREATE TABLE imagenes (id INT, foto IMAGE)")
        self.execute(f"INSERT INTO imagenes VALUES (0, '{self.path('img0.png')}'), (9, '{self.path('gris.png')}')")
        self.execute("CREATE INDEX imagenes_foto ON imagenes (foto) USING HNSW WITH (METRIC = cosine)")
        # Con el coseno el vector nulo no se indexa; la fila sigue en la tabla.
        rows = self.execute(f"SELECT id FROM imagenes WHERE SIMILAR_TO('{self.path('img0.png')}', k=5) USING HNSW")
        self.assertEqual(rows, [(0,)])
        self.assertEqual(self.execute("SELECT COUNT(*) FROM imagenes"), [(2,)])


class TestMissingVocabulary(unittest.TestCase):
    def test_explains_how_to_train_it(self):
        with tempfile.TemporaryDirectory() as empty, patch("engine.features.registry.MODELS_DIR", Path(empty)), \
                patch.dict("engine.features.registry._extractors", clear=True):
            with self.assertRaisesRegex(FileNotFoundError, "train_codebook.py --kind audio"):
                extract_features("audio", "x.wav")


if __name__ == "__main__":
    unittest.main()
