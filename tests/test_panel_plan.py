import shutil
import tempfile
import unittest

import frontend.motor as motor_module
from frontend.panel_plan_ejecucion import desvio_estimacion, filas_analisis


class TestAnalisisDelPlan(unittest.TestCase):
    def setUp(self):
        demo = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, demo, True)
        original = motor_module.DEMO_DIR
        motor_module.DEMO_DIR = demo
        self.addCleanup(setattr, motor_module, "DEMO_DIR", original)
        self.motor = motor_module.Motor()
        self.addCleanup(self.motor.cerrar)
        self.motor.ejecutar("CREATE TABLE t (id INT PRIMARY KEY, g INT);")
        self.motor.ejecutar("INSERT INTO t VALUES " + ", ".join(f"({i}, {i % 4})" for i in range(200)) + ";")

    def test_explain_analyze_entrega_el_arbol_como_datos(self):
        resultado = self.motor.ejecutar("EXPLAIN ANALYZE SELECT g, COUNT(*) FROM t GROUP BY g ORDER BY g;")
        self.assertEqual(resultado.columnas, ["QUERY PLAN"])
        nodos = resultado.plan_nodos
        self.assertEqual([(n["depth"], n["label"]) for n in nodos],
                         [(0, "Sort"), (1, "HashAggregate"), (2, "Seq Scan on t")])
        self.assertEqual(nodos[1]["rows"], 4)  # grupos estimados con los valores distintos reales
        self.assertEqual(nodos[1]["actual"]["rows"], 4)
        self.assertEqual(nodos[0]["startup"], nodos[0]["cost"])
        self.assertIn("Sort Method: in-memory", nodos[0]["details"])
        self.assertIsNotNone(resultado.tiempos[1])

        filas = filas_analisis(nodos)
        incl = [float(f[2][5]) for f in filas]
        excl = [float(f[2][4]) for f in filas]
        self.assertAlmostEqual(excl[0], max(0.0, incl[0] - incl[1]), places=3)
        self.assertEqual(filas[2][3], "")  # estimación exacta: sin resaltar

    def test_explain_sin_analyze_no_tiene_valores_reales(self):
        resultado = self.motor.ejecutar("EXPLAIN SELECT * FROM t WHERE id = 3;")
        self.assertIsNone(resultado.tiempos[1])
        (fila,) = [f for f in filas_analisis(resultado.plan_nodos)]
        self.assertEqual(fila[2][2:], ("", "", "", "", ""))

    def test_desvio_y_resaltado(self):
        self.assertEqual(desvio_estimacion(4, 6), (1.5, "↑"))
        self.assertEqual(desvio_estimacion(100, 5), (20.0, "↓"))
        nodos = [{"depth": 0, "label": "Seq Scan on t", "startup": 0.0, "cost": 1.0, "rows": 100,
                  "details": [], "actual": {"first": 0.0, "total": 0.001, "rows": 5, "loops": 1}}]
        self.assertEqual(filas_analisis(nodos)[0][3], "alto")
        nodos.insert(0, {"depth": 0, "label": "Limit", "startup": 0.0, "cost": 1.0, "rows": 5,
                         "details": [], "actual": {"first": 0.0, "total": 0.001, "rows": 5, "loops": 1}})
        nodos[1]["depth"] = 1
        self.assertEqual(filas_analisis(nodos)[1][3], "")  # el Limit cortó la entrada


if __name__ == "__main__":
    unittest.main()
