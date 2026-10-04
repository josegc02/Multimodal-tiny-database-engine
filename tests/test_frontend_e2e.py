"""Pruebas de punta a punta por la fachada del frontend (Motor) y la ventana Tk.

Recorre cada almacenamiento (HEAP, SEQUENTIAL, BTREE agrupado) combinado con
cada índice secundario (ninguno, HASH, BTREE no agrupado) y compara cada
consulta con el resultado calculado en Python sobre los mismos datos.
"""

import csv
import os
import random
import shutil
import tempfile
import unittest

import frontend.motor as motor_module

STORAGES = ("HEAP", "SEQUENTIAL", "BTREE")
INDEXES = (None, "HASH", "BTREE")
N = 1500


class DemoDirMixin:
    def use_temp_demo_dir(self):
        demo = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, demo, True)
        original = motor_module.DEMO_DIR
        motor_module.DEMO_DIR = demo
        self.addCleanup(setattr, motor_module, "DEMO_DIR", original)
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)


class TestTodosLosModelos(DemoDirMixin, unittest.TestCase):
    def setUp(self):
        self.use_temp_demo_dir()
        self.motor = motor_module.Motor()
        self.addCleanup(self.motor.cerrar)

    def sql(self, query):
        resultado = self.motor.ejecutar(query)
        self.assertFalse(resultado.tiene_error, f"{query}\n-> {resultado.error}")
        return resultado

    def filas(self, query):
        return self.sql(query).filas

    def error(self, query):
        resultado = self.motor.ejecutar(query)
        self.assertTrue(resultado.tiene_error, f"se esperaba error: {query}")
        return resultado.error

    def cargar(self, storage, index):
        rng = random.Random(f"{storage}-{index}")
        self.sql("CREATE TABLE deptos (id INT PRIMARY KEY, nombre VARCHAR(10));")
        self.sql("INSERT INTO deptos VALUES (1, 'Ventas'), (2, 'TI'), (3, 'RRHH'), (4, 'Legal');")
        self.sql("CREATE TABLE emp (id INT PRIMARY KEY, nombre VARCHAR(12), depto INT REFERENCES deptos(id) "
                 f"ON DELETE CASCADE, salario INT, bono FLOAT) USING {storage};")
        if index:
            self.sql(f"CREATE INDEX emp_sal ON emp USING {index} (salario);")
        ids = list(range(1, N + 1))
        rng.shuffle(ids)
        rows = {i: (i, f"e{i}", rng.randint(1, 4), rng.randint(1000, 100999), round(rng.random() * 10, 2))
                for i in ids}
        # Mitad por INSERT (en lotes) y mitad por COPY desde CSV.
        mitad = ids[:N // 2]
        for start in range(0, len(mitad), 250):
            values = ", ".join(f"({i}, 'e{i}', {rows[i][2]}, {rows[i][3]}, {rows[i][4]})"
                               for i in mitad[start:start + 250])
            self.sql(f"INSERT INTO emp VALUES {values};")
        path = os.path.join(self.dir, "emp.csv")
        with open(path, "w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(["id", "nombre", "depto", "salario", "bono"])
            for i in ids[N // 2:]:
                writer.writerow(rows[i])
        self.assertEqual(self.sql(f"COPY emp FROM '{path.replace(os.sep, '/')}' WITH (FORMAT csv, HEADER);").mensaje,
                         f"COPY {N - N // 2}")
        return rows

    def verificar(self, storage, index):
        rows = self.cargar(storage, index)
        data = list(rows.values())

        # Igualdad por PK y por la columna indexada.
        self.assertEqual(self.filas("SELECT * FROM emp WHERE id = 77;"), [rows[77]])
        objetivo = rows[123][3]
        self.assertEqual(sorted(self.filas(f"SELECT id FROM emp WHERE salario = {objetivo};")),
                         sorted((r[0],) for r in data if r[3] == objetivo))
        # Rango, orden y límite.
        self.assertEqual(self.filas("SELECT id FROM emp WHERE salario BETWEEN 50000 AND 50999 ORDER BY id;"),
                         [(r[0],) for r in sorted(data) if 50000 <= r[3] <= 50999])
        self.assertEqual(self.filas("SELECT id, salario FROM emp ORDER BY salario DESC, id LIMIT 7;"),
                         [(r[0], r[3]) for r in sorted(data, key=lambda r: (-r[3], r[0]))[:7]])
        self.assertEqual(self.filas(f"SELECT id FROM emp WHERE id > {N - 10} ORDER BY id DESC;"),
                         [(i,) for i in range(N, N - 10, -1)])
        # Agregación, DISTINCT y JOIN.
        esperado = {}
        for r in data:
            esperado.setdefault(r[2], []).append(r[3])
        self.assertEqual(sorted(self.filas("SELECT depto, COUNT(*), MIN(salario), MAX(salario) FROM emp GROUP BY depto;")),
                         sorted((d, len(v), min(v), max(v)) for d, v in esperado.items()))
        self.assertEqual(sorted(self.filas("SELECT DISTINCT depto FROM emp;")), [(d,) for d in sorted(esperado)])
        nombres = {1: "Ventas", 2: "TI", 3: "RRHH", 4: "Legal"}
        self.assertEqual(sorted(self.filas("SELECT d.nombre, COUNT(*) AS n FROM emp e JOIN deptos d "
                                           "ON e.depto = d.id GROUP BY d.nombre;")),
                         sorted((nombres[d], len(v)) for d, v in esperado.items()))

        # Restricciones.
        self.assertIn("emp_pkey", self.error("INSERT INTO emp VALUES (5, 'dup', 1, 1000, 0.0);"))
        self.error(f"INSERT INTO emp VALUES ({N + 1}, 'x', 9, 1000, 0.0);")  # FK inexistente

        # Transacciones: ROLLBACK deshace y COMMIT conserva.
        self.sql(f"BEGIN; DELETE FROM emp WHERE salario < 50000; INSERT INTO emp VALUES ({N + 1}, 'tmp', 1, 1, 0.0); "
                 "ROLLBACK;")
        self.assertEqual(self.filas("SELECT COUNT(*) FROM emp;"), [(N,)])
        self.assertEqual(self.filas(f"SELECT * FROM emp WHERE id = {N + 1};"), [])
        self.sql("BEGIN; DELETE FROM emp WHERE salario < 20000; COMMIT;")
        quedan = [r for r in data if r[3] >= 20000]
        self.assertEqual(self.filas("SELECT COUNT(*) FROM emp;"), [(len(quedan),)])
        self.assertEqual(sorted(self.filas("SELECT id FROM emp WHERE salario BETWEEN 1000 AND 30000;")),
                         sorted((r[0],) for r in quedan if r[3] <= 30000))

        # ON DELETE CASCADE desde la tabla padre.
        self.sql("DELETE FROM deptos WHERE id = 2;")
        quedan = [r for r in quedan if r[2] != 2]
        self.assertEqual(self.filas("SELECT COUNT(*) FROM emp;"), [(len(quedan),)])
        self.assertEqual(self.filas("SELECT COUNT(*) FROM emp WHERE depto = 2;"), [(0,)])

        # EXPLAIN y EXPLAIN ANALYZE: texto en Resultados y árbol para el panel.
        plan = self.sql("EXPLAIN ANALYZE SELECT * FROM emp WHERE salario BETWEEN 60000 AND 60099;")
        self.assertEqual(plan.columnas, ["QUERY PLAN"])
        self.assertTrue(plan.plan_nodos and plan.plan_nodos[0]["actual"] is not None)
        reales = sum(1 for r in quedan if 60000 <= r[3] <= 60099)
        self.assertEqual(plan.plan_nodos[0]["actual"]["rows"], reales)
        if index == "BTREE":
            self.assertTrue(plan.plan[0].startswith("Index Scan using emp_sal"), plan.plan[0])
        if index == "HASH":
            igualdad = self.sql(f"EXPLAIN SELECT * FROM emp WHERE salario = {quedan[0][3]};")
            self.assertTrue(igualdad.plan[0].startswith("Index Scan using emp_sal"), igualdad.plan[0])
        pk = self.sql("EXPLAIN SELECT * FROM emp WHERE id = 300;")
        self.assertTrue(pk.plan[0].startswith("Index Scan"), pk.plan[0])

    def test_matriz_almacenamiento_por_indice(self):
        for storage in STORAGES:
            for index in INDEXES:
                with self.subTest(storage=storage, index=index):
                    self.motor.cerrar()
                    self.motor = motor_module.Motor()
                    self.verificar(storage, index)


class TestVentanaTk(DemoDirMixin, unittest.TestCase):
    """Maneja la ventana real (se omite si no hay pantalla, p. ej. en CI Linux)."""

    def setUp(self):
        self.use_temp_demo_dir()
        import tkinter
        from frontend.main import Aplicacion
        try:
            self.app = Aplicacion()
        except tkinter.TclError as error:
            self.skipTest(f"sin pantalla: {error}")
        self.app.withdraw()
        self.addCleanup(self.app._on_cerrar)

    def ejecutar(self, sql):
        self.app.panel_consultas.set_sql(sql)
        self.app.panel_consultas.ejecutar()
        self.app.update()
        return self.app.panel_resultados

    def test_flujo_completo_en_la_ventana(self):
        app = self.app
        self.assertIn("Tabla: cuentas", app.panel_archivos.texto_esquema.get("1.0", "end"))

        resultados = self.ejecutar("CREATE TABLE t (id INT PRIMARY KEY, v INT) USING SEQUENTIAL; "
                                   "INSERT INTO t VALUES (3, 30), (1, 10), (2, 20);")
        self.assertIn("t", app.panel_archivos.lista.get(0, "end"))

        resultados = self.ejecutar("SELECT * FROM t ORDER BY id;")
        filas = [resultados.tree.item(i, "values") for i in resultados.tree.get_children()]
        self.assertEqual(filas, [("1", "10"), ("2", "20"), ("3", "30")])
        self.assertEqual(resultados.mensaje.cget("text"), "3 fila(s)")
        self.assertFalse(app.panel_plan.frame_arbol.winfo_ismapped())

        resultados = self.ejecutar("INSERT INTO t VALUES (1, 99);")
        self.assertTrue(resultados.mensaje.cget("text").startswith("Error:"))

        resultados = self.ejecutar("EXPLAIN ANALYZE SELECT v, COUNT(*) FROM t GROUP BY v ORDER BY v;")
        self.assertEqual(str(resultados.tree.cget("style")), "Plan.Treeview")
        lineas = [resultados.tree.item(i, "values")[0] for i in resultados.tree.get_children()]
        self.assertTrue(lineas[0].startswith("Sort"))
        arbol = app.panel_plan.arbol
        raiz = arbol.get_children()
        self.assertEqual(arbol.item(raiz[0], "text"), "Sort")
        self.assertIn("Execution Time", app.panel_plan.pie.cget("text"))

        # El botón Cargar CSV escribe el SQL en el editor (sin el diálogo de archivos).
        from frontend.csv_sql import sql_para_csv
        path = os.path.join(self.dir, "ventas.csv")
        with open(path, "w", encoding="utf-8") as stream:
            stream.write("id,monto\n1,10.5\n2,20\n")
        app.panel_consultas.set_sql(sql_para_csv(path, app.panel_consultas.obtener_tablas()))
        app.panel_consultas.ejecutar()
        app.update()
        filas = [resultados.tree.item(i, "values") for i in resultados.tree.get_children()]
        self.assertEqual(sorted(filas), [("1", "10.5"), ("2", "20.0")])


if __name__ == "__main__":
    unittest.main()
