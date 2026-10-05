import errno
import json
import shutil
import tempfile
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen

import frontend.motor as motor_module
from frontend.panel_mapa import MapServer


class TestMapServer(unittest.TestCase):
    def setUp(self):
        self.clicked = []
        try:
            self.server = MapServer(lambda lat, lon: self.clicked.append((lat, lon)))
        except PermissionError as error:
            if error.errno == errno.EPERM:
                self.skipTest("sandbox sin sockets locales")
            raise
        self.addCleanup(self.server.close)

    def get(self, path):
        return urlopen(self.server.url + path).read().decode()

    def test_page_state_version_and_click(self):
        self.assertIn("leaflet", self.get("").lower())
        before = json.loads(self.get("api/version"))["version"]
        points = [(1, -12.0, -77.0, "uno")]
        self.server.publish(table="t", points=points, highlighted=[1])
        self.assertEqual(json.loads(self.get("api/version"))["version"], before + 1)
        state = json.loads(self.get("api/state"))
        self.assertEqual(state["points"], [{"id": 1, "lat": -12.0, "lon": -77.0, "label": "uno"}])
        self.assertEqual(state["highlighted"], [1])

        request = Request(self.server.url + "api/click", data=b'{"lat":-12.1,"lng":-77.1}',
                          headers={"Content-Type": "application/json"}, method="POST")
        urlopen(request).read()
        self.assertEqual(self.clicked, [(-12.1, -77.1)])

    def test_points_are_serialized_once_per_list(self):
        points = [(i, -12.0, -77.0, str(i)) for i in range(3)]
        self.server.publish(points=points)
        with patch("frontend.panel_mapa.json.dumps", wraps=json.dumps) as dumps:
            self.server.publish(points=points, highlighted=[2])  # misma lista: no se vuelve a serializar
        self.assertEqual(dumps.call_count, 1)
        self.assertEqual(json.loads(self.get("api/state"))["highlighted"], [2])


class TestMapPayload(unittest.TestCase):
    def setUp(self):
        demo = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, demo, True)
        patcher = patch.object(motor_module, "DEMO_DIR", demo)
        patcher.start()
        # Las limpiezas corren en orden inverso: el motor se cierra antes de borrar el directorio.
        self.addCleanup(patcher.stop)
        self.motor = motor_module.Motor()
        self.addCleanup(self.motor.cerrar)
        self.sql("CREATE TABLE tiendas (id INT PRIMARY KEY, cat VARCHAR(5), p POINT)")
        self.sql("INSERT INTO tiendas VALUES (1, 'a', POINT(-12, -77)), (2, 'b', POINT(-12.2, -77.2))")

    def sql(self, query):
        result = self.motor.ejecutar(query)
        self.assertFalse(result.tiene_error, result.error)
        return result

    def test_radius_polygon_and_knn_figures(self):
        mapa = self.sql("SELECT id FROM tiendas WHERE distancia(p, POINT(-12, -77)) < 5000 AND cat = 'a'").mapa
        self.assertEqual(mapa["result_ids"], [1])
        self.assertEqual(mapa["circle"], {"lat": -12, "lon": -77, "radius": 5000})
        self.assertEqual(len(mapa["points"]), 2)

        mapa = self.sql("SELECT id FROM tiendas WHERE WITHIN(p, POLYGON((-13, -78), (-11, -78), (-11, -76)))").mapa
        self.assertEqual(mapa["result_ids"], [1, 2])
        self.assertEqual(mapa["polygon"], [(-13, -78), (-11, -78), (-11, -76)])

        mapa = self.sql("SELECT id FROM tiendas ORDER BY distancia(p, POINT(-12.1, -77.1)) LIMIT 1").mapa
        self.assertEqual(mapa["circle"], {"lat": -12.1, "lon": -77.1, "radius": 0})

    def test_points_are_cached_until_a_write(self):
        # Con R-Tree la consulta no recorre la tabla: el único scan posible sería el del mapa.
        self.sql("CREATE INDEX tiendas_geo ON tiendas (p) USING RTREE")
        self.sql("SELECT id FROM tiendas")
        binding = self.motor.catalog.table("tiendas")
        with patch.object(binding.storage, "scan", side_effect=AssertionError("el mapa no debe releer la tabla")):
            self.sql("SELECT id FROM tiendas WHERE distancia(p, POINT(-12, -77)) < 1000")
        self.sql("INSERT INTO tiendas VALUES (3, 'c', POINT(-12.1, -77.1))")
        self.assertEqual(len(self.sql("SELECT id FROM tiendas").mapa["points"]), 3)

    def test_tables_without_points_do_not_touch_the_map(self):
        self.sql("CREATE TABLE plana (id INT PRIMARY KEY)")
        self.assertIsNone(self.sql("SELECT * FROM plana").mapa)


if __name__ == "__main__":
    unittest.main()
