"""API REST del motor (#96)."""

import os
import tempfile
import threading
import unittest
from unittest.mock import patch

import numpy as np

try:
    from fastapi.testclient import TestClient
    from api.main import create_app
except ImportError:  # pragma: no cover - dependencia de requirements-api.txt
    TestClient = None

ORIGEN = "http://localhost:5173"


def fake_extract(kind, path):
    vectores = {"gato.jpg": [1.0, 0.0], "gato2.jpg": [0.9, 0.1], "perro.jpg": [0.0, 1.0]}
    return np.asarray(vectores[os.path.basename(path)], dtype=np.float32)


@unittest.skipIf(TestClient is None, "requiere requirements-api.txt")
class TestAPI(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.datos = os.path.join(temp.name, "datos")
        self.fotos = os.path.join(temp.name, "fotos")
        os.makedirs(self.fotos)
        for nombre in ("gato.jpg", "gato2.jpg", "perro.jpg", "notas.txt"):
            with open(os.path.join(self.fotos, nombre), "wb") as fh:
                fh.write(b"contenido de " + nombre.encode())
        with open(os.path.join(temp.name, "secreto.jpg"), "wb") as fh:
            fh.write(b"fuera de las carpetas permitidas")
        patcher = patch("engine.storage.media_store.extract_features", fake_extract)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.cliente = self.abrir()

    def abrir(self):
        cliente = TestClient(create_app(directorio=self.datos, carpetas_archivos=[self.fotos],
                                        origenes=[ORIGEN]))
        cliente.__enter__()
        self.addCleanup(cliente.__exit__, None, None, None)
        return cliente

    def foto(self, nombre):
        return os.path.join(self.fotos, nombre).replace("\\", "/")

    def sql(self, sql, estado=200):
        respuesta = self.cliente.post("/sql", json={"sql": sql})
        self.assertEqual(respuesta.status_code, estado, respuesta.text)
        return respuesta.json()

    # --- /salud y /sql -------------------------------------------------

    def test_salud(self):
        self.assertEqual(self.cliente.get("/salud").json(), {"ok": True, "tablas": 0})

    def test_sql_devuelve_columnas_filas_y_point_como_objeto(self):
        datos = self.sql("CREATE TABLE tiendas (id INT PRIMARY KEY, nombre VARCHAR(20), ubicacion POINT);"
                         "INSERT INTO tiendas VALUES (1, 'Centro', POINT(-12.05, -77.04))")
        self.assertIn("Tabla tiendas creada", datos["mensaje"])
        datos = self.sql("SELECT id, nombre, ubicacion FROM tiendas")
        self.assertEqual(datos["columnas"], ["id", "nombre", "ubicacion"])
        self.assertEqual(datos["filas"], [[1, "Centro", {"lat": -12.05, "lon": -77.04}]])
        self.assertNotIn("error", datos)

    def test_explain_analyze_devuelve_el_plan(self):
        self.sql("CREATE TABLE t (id INT PRIMARY KEY); INSERT INTO t VALUES (1), (2)")
        datos = self.sql("EXPLAIN ANALYZE SELECT * FROM t WHERE id = 2")
        self.assertEqual(datos["columnas"], ["QUERY PLAN"])
        self.assertTrue(any("Scan" in linea for linea in datos["plan"]), datos["plan"])
        self.assertIsNotNone(datos["tiempos"]["ejecucion"])

    def test_errores_responden_400_con_mensaje(self):
        self.assertIn("sintaxis", self.sql("SELEC 1", 400)["error"])
        self.assertIn("no existe", self.sql("SELECT * FROM fantasma", 400)["error"])
        self.assertEqual(self.cliente.post("/sql", json={}).status_code, 422)

    def test_similar_to_devuelve_puntajes_numericos(self):
        filas = ", ".join(f"({i}, '{self.foto(n)}')" for i, n in enumerate(("gato.jpg", "gato2.jpg", "perro.jpg")))
        self.sql(f"CREATE TABLE fotos (id INT PRIMARY KEY, foto IMAGE); INSERT INTO fotos VALUES {filas};"
                 "CREATE INDEX fotos_foto ON fotos (foto) USING HNSW WITH (METRIC = cosine)")
        datos = self.sql(f"SELECT id, SIMILARITY_SCORE() AS s FROM fotos "
                         f"WHERE SIMILAR_TO('{self.foto('gato.jpg')}', k=2) USING HNSW")
        self.assertEqual([fila[0] for fila in datos["filas"]], [0, 1])
        self.assertTrue(all(isinstance(fila[1], float) for fila in datos["filas"]))

    # --- Transacciones: cada petición es autocommit ----------------------

    def test_transaccion_abierta_se_deshace(self):
        self.sql("CREATE TABLE t (id INT)")
        error = self.sql("BEGIN; INSERT INTO t VALUES (1)", 400)["error"]
        self.assertIn("se deshizo", error)
        self.assertEqual(self.sql("SELECT COUNT(*) AS n FROM t")["filas"], [[0]])
        # Un BEGIN suelto tampoco deja la sesión dentro de una transacción.
        self.sql("BEGIN", 400)
        self.sql("INSERT INTO t VALUES (2)")
        self.assertEqual(self.sql("SELECT COUNT(*) AS n FROM t")["filas"], [[1]])

    def test_transaccion_completa_en_un_script(self):
        self.sql("CREATE TABLE t (id INT)")
        self.sql("BEGIN; INSERT INTO t VALUES (1); COMMIT")
        self.sql("BEGIN; INSERT INTO t VALUES (2); ROLLBACK")
        self.assertEqual(self.sql("SELECT id FROM t")["filas"], [[1]])

    def test_error_dentro_de_transaccion_la_deshace(self):
        self.sql("CREATE TABLE t (id INT PRIMARY KEY)")
        self.sql("BEGIN; INSERT INTO t VALUES (1); INSERT INTO t VALUES (1); COMMIT", 400)
        self.assertEqual(self.sql("SELECT COUNT(*) AS n FROM t")["filas"], [[0]])

    def test_peticiones_simultaneas(self):
        self.sql("CREATE TABLE t (id INT PRIMARY KEY, hilo INT)")
        errores = []

        def insertar(hilo):
            for i in range(10):
                r = self.cliente.post("/sql", json={"sql": f"INSERT INTO t VALUES ({hilo * 100 + i}, {hilo})"})
                if r.status_code != 200:
                    errores.append(r.text)

        hilos = [threading.Thread(target=insertar, args=(h,)) for h in range(8)]
        for hilo in hilos:
            hilo.start()
        for hilo in hilos:
            hilo.join()
        self.assertEqual(errores, [])
        self.assertEqual(self.sql("SELECT COUNT(*) AS n FROM t")["filas"], [[80]])

    # --- Persistencia ----------------------------------------------------

    def test_los_datos_sobreviven_al_reiniciar(self):
        self.sql("CREATE TABLE t (id INT PRIMARY KEY, nombre VARCHAR(10)); INSERT INTO t VALUES (1, 'Ana')")
        self.cliente.__exit__(None, None, None)
        self.cliente = self.abrir()
        self.assertEqual(self.sql("SELECT nombre FROM t WHERE id = 1")["filas"], [["Ana"]])

    # --- /tablas ---------------------------------------------------------

    def test_tablas_describe_almacenamiento_columnas_e_indices(self):
        self.sql("CREATE TABLE carreras (id INT PRIMARY KEY, nombre VARCHAR(20)) USING BTREE;"
                 "CREATE TABLE alumnos (id INT PRIMARY KEY, nota FLOAT) USING SEQUENTIAL;"
                 "CREATE TABLE docs (id INT PRIMARY KEY, texto TEXT, lugar POINT, foto IMAGE);"
                 "CREATE INDEX alumnos_nota ON alumnos (nota) USING BTREE;"
                 "CREATE INDEX docs_texto ON docs (texto) USING SPIMI;"
                 "CREATE INDEX docs_lugar ON docs (lugar) USING RTREE;"
                 "CREATE INDEX docs_foto ON docs (foto) USING IVF;"
                 "INSERT INTO carreras VALUES (1, 'CS')")
        tablas = {t["nombre"]: t for t in self.cliente.get("/tablas").json()}
        self.assertEqual(sorted(tablas), ["alumnos", "carreras", "docs"])
        self.assertEqual((tablas["carreras"]["almacenamiento"], tablas["alumnos"]["almacenamiento"],
                          tablas["docs"]["almacenamiento"]), ("btree", "sequential", "heap"))
        self.assertEqual(tablas["carreras"]["filas_estimadas"], 1)
        self.assertEqual(tablas["carreras"]["columnas"],
                         [{"nombre": "id", "tipo": "INT"}, {"nombre": "nombre", "tipo": "VARCHAR(20)"}])
        self.assertEqual([c["tipo"] for c in tablas["docs"]["columnas"]], ["INT", "TEXT", "POINT", "IMAGE"])
        metodos = {t: {i["nombre"]: i["metodo"] for i in tablas[t]["indices"]} for t in tablas}
        self.assertEqual(metodos["carreras"], {"carreras_pkey": "btree agrupado"})
        self.assertEqual(metodos["alumnos"], {"alumnos_pkey": "secuencial", "alumnos_nota": "btree"})
        self.assertEqual(metodos["docs"], {"docs_pkey": "hash", "docs_texto": "spimi",
                                           "docs_lugar": "rtree", "docs_foto": "ivf"})

    # --- /archivos -------------------------------------------------------

    def test_archivos_sirve_solo_desde_carpetas_permitidas(self):
        respuesta = self.cliente.get("/archivos", params={"ruta": self.foto("gato.jpg")})
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.content, b"contenido de gato.jpg")
        self.assertTrue(respuesta.headers["content-type"].startswith("image/jpeg"))

        escape = self.foto("../secreto.jpg")
        for ruta, estado in ((escape, 403), (self.foto("notas.txt"), 403), (self.foto("no_existe.jpg"), 404)):
            with self.subTest(ruta=ruta):
                respuesta = self.cliente.get("/archivos", params={"ruta": ruta})
                self.assertEqual(respuesta.status_code, estado)
                self.assertIn("error", respuesta.json())

    # --- CORS ------------------------------------------------------------

    def test_cors_solo_para_el_origen_configurado(self):
        cabeceras = {"Access-Control-Request-Method": "POST"}
        permitido = self.cliente.options("/sql", headers={"Origin": ORIGEN, **cabeceras})
        self.assertEqual(permitido.headers.get("access-control-allow-origin"), ORIGEN)
        ajeno = self.cliente.options("/sql", headers={"Origin": "http://otro.com", **cabeceras})
        self.assertNotIn("access-control-allow-origin", ajeno.headers)


if __name__ == "__main__":
    unittest.main()
