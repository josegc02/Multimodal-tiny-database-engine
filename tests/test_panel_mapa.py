import shutil
import tempfile
import unittest
from unittest.mock import patch

import frontend.motor as motor_module
from frontend.mapa_datos import LADO_MINIMO_ENCUADRE, LIMITE_CONTEXTO, MAX_MARCADORES, encuadre, seleccionar_puntos


class TestSeleccionarPuntos(unittest.TestCase):
    @staticmethod
    def puntos(n):
        return [(i, -12.0, -77.0, str(i)) for i in range(n)]

    def test_tabla_pequena_conserva_el_contexto(self):
        puntos = self.puntos(LIMITE_CONTEXTO - 1)
        self.assertEqual(seleccionar_puntos(puntos, {1}), puntos)

    def test_tabla_grande_dibuja_solo_resultados(self):
        elegidos = seleccionar_puntos(self.puntos(LIMITE_CONTEXTO), {1, 2})
        self.assertEqual([p[0] for p in elegidos], [1, 2])

    def test_select_amplio_no_supera_el_tope(self):
        puntos = self.puntos(10_000)
        elegidos = seleccionar_puntos(puntos, {p[0] for p in puntos})
        self.assertEqual(len(elegidos), MAX_MARCADORES)


class TestEncuadre(unittest.TestCase):
    def test_sin_coordenadas(self):
        self.assertIsNone(encuadre([]))

    def test_contiene_las_coordenadas_con_margen(self):
        (norte, oeste), (sur, este) = encuadre([(-12, -77), (-5, -80)])
        self.assertGreater(norte, -5)
        self.assertLess(sur, -12)
        self.assertLess(oeste, -80)
        self.assertGreater(este, -77)

    def test_un_punto_da_una_caja_valida(self):
        (norte, oeste), (sur, este) = encuadre([(-12, -77)])
        self.assertGreater(norte, sur)  # fit_bounding_box rechaza cajas sin extensión
        self.assertLess(oeste, este)
        self.assertGreaterEqual(norte - sur, LADO_MINIMO_ENCUADRE)


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
