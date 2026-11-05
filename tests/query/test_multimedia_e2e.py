"""SQL multimedia con los extractores reales: SIFT para IMAGE y MFCC para AUDIO."""

import os
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

try:
    import cv2
    import soundfile
except ImportError:  # pragma: no cover - dependencia opcional del entorno
    cv2 = soundfile = None

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
        self.assertEqual(schema.vector("foto", self.path("img0.png")).shape, (128,))
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


if __name__ == "__main__":
    unittest.main()
