import json
import errno
import tempfile
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen

from frontend.motor import Motor
from frontend.panel_mapa import MapServer


class TestMapServer(unittest.TestCase):
    def test_leaflet_api_and_click_callback(self):
        clicked = []
        try:
            server = MapServer(lambda lat, lon: clicked.append((lat, lon)))
        except PermissionError as error:
            if error.errno == errno.EPERM:
                self.skipTest("sandbox sin sockets locales")
            raise
        self.addCleanup(server.close)
        server.state["points"] = [{"id": 1, "lat": -12.0, "lon": -77.0, "label": "uno"}]
        self.assertIn("leaflet", urlopen(server.url).read().decode().lower())
        state = json.loads(urlopen(server.url + "api/state").read())
        self.assertEqual(state["points"][0]["id"], 1)
        request = Request(server.url + "api/click", data=b'{"lat":-12.1,"lng":-77.1}',
                          headers={"Content-Type": "application/json"}, method="POST")
        urlopen(request).read()
        self.assertEqual(clicked, [(-12.1, -77.1)])


class TestMapPayload(unittest.TestCase):
    def test_select_payload_has_points_results_circle_and_polygon(self):
        with tempfile.TemporaryDirectory() as directory, patch("frontend.motor.DEMO_DIR", directory):
            motor = Motor()
            self.addCleanup(motor.cerrar)
            for sql in ["CREATE TABLE tiendas (id INT PRIMARY KEY, p POINT)",
                        "INSERT INTO tiendas VALUES (1,POINT(-12,-77)),(2,POINT(-12.2,-77.2))",
                        "SELECT id FROM tiendas WHERE distancia(p,POINT(-12,-77)) < 5000",
                        "SELECT id FROM tiendas WHERE WITHIN(p,POLYGON((-13,-78),(-11,-78),(-11,-76)))"]:
                result = motor.ejecutar(sql)
                self.assertFalse(result.tiene_error, result.error)
            self.assertEqual(result.mapa["result_ids"], [1, 2])
            self.assertEqual(len(result.mapa["points"]), 2)
            self.assertIsNotNone(result.mapa["polygon"])
