"""Motor fuera del modo demo: las tablas e índices sobreviven al reiniciar."""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from frontend.motor import ARCHIVO_CATALOGO, Motor

# Vectores conocidos por ruta; cuenta las extracciones para comprobar que
# reabrir no vuelve a extraer los vectores de IMAGE / AUDIO.
VECTORS = {
    "img/gato.jpg": [1.0, 0.0, 0.0],
    "img/gato2.jpg": [0.9, 0.1, 0.0],
    "img/perro.jpg": [0.0, 1.0, 0.0],
    "img/ave.jpg": [0.0, 0.0, 1.0],
    "img/consulta.jpg": [0.96, 0.04, 0.0],
    "aud/a.wav": [1.0, 2.0],
    "aud/b.wav": [2.0, 1.0],
    "aud/c.wav": [5.0, 5.0],
}
EXTRACCIONES = []


def fake_extract(kind, path):
    EXTRACCIONES.append(path)
    return np.asarray(VECTORS[path], dtype=np.float32)


SCRIPT = """
CREATE TABLE carreras (id INT PRIMARY KEY, nombre VARCHAR(20)) USING BTREE;
CREATE TABLE alumnos (id INT PRIMARY KEY, nombre VARCHAR(20), nota INT,
                      carrera INT REFERENCES carreras(id) ON DELETE CASCADE) USING SEQUENTIAL;
CREATE TABLE tiendas (id INT PRIMARY KEY, nombre VARCHAR(20), ubicacion POINT, descripcion TEXT,
                      foto IMAGE, jingle AUDIO);
CREATE INDEX alumnos_nota ON alumnos (nota) USING BTREE;
CREATE INDEX alumnos_nombre ON alumnos (nombre) USING HASH;
CREATE INDEX tiendas_geo ON tiendas (ubicacion) USING RTREE;
CREATE INDEX tiendas_texto ON tiendas (descripcion) USING SPIMI;
CREATE INDEX tiendas_foto ON tiendas (foto) USING HNSW WITH (METRIC = cosine);
CREATE INDEX tiendas_jingle ON tiendas (jingle) USING IVF;
INSERT INTO carreras VALUES (1, 'CS'), (2, 'Datos');
INSERT INTO alumnos VALUES (1, 'Ana', 18, 1), (2, 'Bruno', 12, 2), (3, 'Carla', 15, 1);
INSERT INTO tiendas VALUES
  (1, 'Centro', POINT(-12.0464, -77.0428), 'venta de laptops y mouses', 'img/gato.jpg', 'aud/a.wav'),
  (2, 'Miraflores', POINT(-12.1211, -77.0297), 'audífonos y parlantes', 'img/perro.jpg', 'aud/b.wav'),
  (3, 'Callao', POINT(-12.0566, -77.1181), 'laptops gamer', 'img/gato2.jpg', 'aud/c.wav'),
  (4, 'Surco', POINT(-12.1500, -76.9900), 'mochilas', 'img/ave.jpg', 'aud/a.wav')
"""

CONSULTAS = [
    "SELECT id, nombre FROM carreras ORDER BY id",
    "SELECT id, nombre, nota, carrera FROM alumnos WHERE nota >= 15 ORDER BY id",
    "SELECT id FROM alumnos WHERE nombre = 'Bruno'",
    "SELECT a.nombre, c.nombre FROM alumnos a JOIN carreras c ON a.carrera = c.id ORDER BY a.nombre",
    "SELECT id FROM tiendas WHERE distancia(ubicacion, POINT(-12.0464, -77.0428)) < 10000 ORDER BY id",
    "SELECT id FROM tiendas ORDER BY distancia(ubicacion, POINT(-12.12, -77.03)) LIMIT 2",
    "SELECT id, SCORE() AS s FROM tiendas WHERE MATCH(descripcion, 'laptops') USING BM25 ORDER BY s DESC",
    "SELECT id, SIMILARITY_SCORE() AS s FROM tiendas WHERE SIMILAR_TO(foto, 'img/consulta.jpg', k=2) "
    "USING HNSW WITH METRIC=cosine",
    "SELECT id FROM tiendas WHERE SIMILAR_TO(jingle, 'aud/a.wav', k=2) USING IVF",
    "SELECT descripcion, foto, ubicacion FROM tiendas WHERE id = 3",
]


class TestMotorPersistente(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = self.temp.name
        patcher = patch("engine.storage.media_store.extract_features", fake_extract)
        patcher.start()
        self.addCleanup(patcher.stop)
        EXTRACCIONES.clear()
        self.motor = None
        self.addCleanup(lambda: self.motor and self.motor.cerrar())

    def abrir(self):
        if self.motor is not None:
            self.motor.cerrar()
        self.motor = Motor(directorio=self.dir, modo_demo=False)
        return self.motor

    def execute(self, sql):
        result = self.motor.ejecutar(sql)
        self.assertFalse(result.tiene_error, result.error)
        return result

    def resultados(self):
        return [self.execute(sql).filas for sql in CONSULTAS]

    def test_reabre_tablas_indices_y_datos(self):
        self.abrir()
        self.execute(SCRIPT)
        antes = self.resultados()
        extracciones = len(EXTRACCIONES)

        self.abrir()
        self.assertEqual(sorted(self.motor.catalog.tables), ["alumnos", "carreras", "tiendas"])
        indices = {info.name for info in self.motor.catalog.table("tiendas").index_info()}
        self.assertTrue({"tiendas_geo", "tiendas_texto", "tiendas_foto", "tiendas_jingle"} <= indices)
        self.assertEqual(self.resultados(), antes)
        # La consulta 'img/consulta.jpg' se extrae en cada búsqueda; las filas no.
        nuevas = [ruta for ruta in EXTRACCIONES[extracciones:] if ruta != "img/consulta.jpg"]
        self.assertEqual(nuevas, [])

    def test_cambios_despues_de_reabrir_tambien_persisten(self):
        self.abrir()
        self.execute(SCRIPT)
        self.abrir()
        self.execute("DELETE FROM carreras WHERE id = 2")  # CASCADE borra a Bruno
        self.execute("INSERT INTO alumnos VALUES (4, 'Diego', 20, 1)")
        self.execute("DELETE FROM tiendas WHERE id = 1")
        antes = self.resultados()
        self.assertEqual(self.execute("SELECT id FROM alumnos ORDER BY id").filas, [(1,), (3,), (4,)])

        self.abrir()
        self.assertEqual(self.resultados(), antes)
        # La llave foránea sigue activa tras reabrir.
        self.assertTrue(self.motor.ejecutar("INSERT INTO alumnos VALUES (5, 'Eva', 11, 9)").tiene_error)

    def test_reabrir_no_duplica_el_catalogo(self):
        self.abrir()
        self.execute("CREATE TABLE t (id INT PRIMARY KEY, n INT); CREATE INDEX t_n ON t (n) USING BTREE")
        ruta = os.path.join(self.dir, ARCHIVO_CATALOGO)
        with open(ruta, encoding="utf-8") as fh:
            original = fh.read()
        self.abrir()
        self.abrir()
        with open(ruta, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), original)
        self.assertEqual(len(json.loads(original)["ddl"]), 2)

    def test_resultados_se_convierten_a_json(self):
        self.abrir()
        self.execute(SCRIPT)
        for sql in CONSULTAS + ["EXPLAIN ANALYZE " + CONSULTAS[7], "INSERT INTO carreras VALUES (3, 'IA')"]:
            with self.subTest(sql=sql):
                datos = json.loads(json.dumps(self.execute(sql).a_dict()))
                self.assertIsNone(datos["error"])
        fila = self.execute(CONSULTAS[-1]).a_dict()["filas"][0]
        self.assertEqual(fila, ["laptops gamer", "img/gato2.jpg", {"lat": -12.0566, "lon": -77.1181}])
        puntajes = self.execute(CONSULTAS[7]).a_dict()["filas"]
        self.assertTrue(all(type(s) is float for _, s in puntajes))
        error = self.motor.ejecutar("SELECT * FROM no_existe").a_dict()
        self.assertEqual((error["filas"], bool(error["error"])), ([], True))

    def test_error_al_reabrir_indica_la_entrada(self):
        self.abrir()
        self.execute("CREATE TABLE t (id INT)")
        self.motor.cerrar()
        self.motor = None
        ruta = os.path.join(self.dir, ARCHIVO_CATALOGO)
        with open(ruta, encoding="utf-8") as fh:
            datos = json.load(fh)
        indice = {"tipo": "indice", "name": "malo", "table": "t", "column": "no_existe",
                  "method": "hash", "language": None, "metric": None}
        datos["ddl"].append(indice)
        with open(ruta, "w", encoding="utf-8") as fh:
            json.dump(datos, fh)
        with self.assertRaisesRegex(RuntimeError, "indice 'malo'"):
            Motor(directorio=self.dir, modo_demo=False)
        # Los archivos de la tabla siguen ahí: un error al reabrir no borra datos.
        self.assertTrue(os.path.exists(os.path.join(self.dir, "t.db")))


if __name__ == "__main__":
    unittest.main()
