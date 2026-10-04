import os
import re
import tempfile
import unittest
from unittest.mock import patch

from frontend.motor import Motor


class MotorTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch("frontend.motor.DEMO_DIR", os.path.join(self.tmp.name, "demo"))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.motor = Motor()
        self.addCleanup(self.motor.cerrar)

    def run_sql(self, sql):
        result = self.motor.ejecutar(sql)
        self.assertFalse(result.tiene_error, result.error)
        return result

    def error(self, sql):
        result = self.motor.ejecutar(sql)
        self.assertTrue(result.tiene_error, f"se esperaba un error en: {sql}")
        return result.error

    def csv(self, name, text, encoding="utf-8"):
        path = os.path.join(self.tmp.name, name)
        with open(path, "w", encoding=encoding, newline="") as fh:
            fh.write(text)
        return path.replace("\\", "/")

    def count(self, table):
        return self.run_sql(f"SELECT COUNT(*) AS n FROM {table}").filas[0][0]


class TestPrimaryKey(MotorTestCase):
    def test_duplicate_keys_are_rejected_on_every_storage(self):
        for method in ("HEAP", "SEQUENTIAL", "BTREE"):
            with self.subTest(storage=method):
                table = f"t_{method.lower()}"
                self.run_sql(f"CREATE TABLE {table} (nombre VARCHAR(10), id INT PRIMARY KEY) USING {method}")
                self.run_sql(f"INSERT INTO {table} VALUES ('a', 1), ('b', 2)")
                message = self.error(f"INSERT INTO {table} VALUES ('c', 2)")
                self.assertIn(f'"{table}_pkey"', message)
                self.assertIn("(id)=(2)", message)
                # Duplicado dentro del mismo lote: no se inserta ninguna fila.
                self.error(f"INSERT INTO {table} VALUES ('d', 3), ('e', 3)")
                self.assertEqual(self.count(table), 2)
                # Tras borrar la clave se puede volver a usar.
                self.run_sql(f"DELETE FROM {table} WHERE id = 2")
                self.run_sql(f"INSERT INTO {table} VALUES ('f', 2)")

    def test_table_level_primary_key_orders_sequential_storage(self):
        self.run_sql("CREATE TABLE t (nombre VARCHAR(10), codigo INT, PRIMARY KEY (codigo)) USING SEQUENTIAL")
        self.assertEqual(self.motor.catalog.table("t").storage.key_field, "codigo")
        self.run_sql("INSERT INTO t VALUES ('b', 20), ('a', 10)")
        self.assertEqual(self.error("INSERT INTO t VALUES ('c', 10)").count("t_pkey"), 1)

    def test_heap_primary_key_creates_an_index_used_by_equality(self):
        self.run_sql("CREATE TABLE alumnos (id INT PRIMARY KEY, nombre VARCHAR(20))")
        # Con pocas filas el scan es más barato que el índice; con 3000 ya no.
        values = ", ".join(f"({i}, 'n{i}')" for i in range(3000))
        self.run_sql(f"INSERT INTO alumnos VALUES {values}")
        plan = self.run_sql("EXPLAIN SELECT * FROM alumnos WHERE id = 299").plan
        self.assertTrue(plan[0].startswith("Index Scan using alumnos_pkey on alumnos"))
        self.assertEqual(plan[1], "  Index Cond: (id = 299)")

    def test_rollback_releases_the_key(self):
        self.run_sql("CREATE TABLE t (id INT PRIMARY KEY)")
        self.run_sql("BEGIN; INSERT INTO t VALUES (1); ROLLBACK")
        self.run_sql("INSERT INTO t VALUES (1)")
        self.assertEqual(self.count("t"), 1)


class TestCopy(MotorTestCase):
    def setUp(self):
        super().setUp()
        self.run_sql("CREATE TABLE alumnos (id INT PRIMARY KEY, nombre VARCHAR(100), carrera_id INT, nota INT)")

    def test_copy_with_header_quotes_accents_and_bom(self):
        path = self.csv("a.csv", '﻿id,nombre,carrera_id,nota\n1,"Pérez, Juan",3,15\n2,"Díaz ""Pepe""",1,12\n\n')
        self.assertEqual(self.run_sql(f"COPY alumnos FROM '{path}' WITH (FORMAT csv, HEADER true)").mensaje,
                         "COPY 2")
        rows = self.run_sql("SELECT * FROM alumnos WHERE nombre = 'Pérez, Juan'").filas
        self.assertEqual(rows, [(1, "Pérez, Juan", 3, 15)])
        self.assertEqual(self.run_sql("SELECT nombre FROM alumnos WHERE id = 2").filas, [('Díaz "Pepe"',)])

    def test_copy_delimiter_column_order_and_classic_syntax(self):
        path = self.csv("b.csv", "nota;id;carrera_id;nombre\n17;5;2;Ana\n")
        self.run_sql(f"COPY alumnos (nota, id, carrera_id, nombre) FROM '{path}' WITH (FORMAT csv, HEADER, DELIMITER ';')")
        self.assertEqual(self.run_sql("SELECT * FROM alumnos").filas, [(5, "Ana", 2, 17)])
        path = self.csv("c.csv", "6,Bob,1,9\n")
        self.assertEqual(self.run_sql(f"COPY alumnos FROM '{path}' CSV").mensaje, "COPY 1")

    def test_invalid_rows_report_the_line_and_load_nothing(self):
        cases = {
            "1,Ana,1,15\n2,Bob,1,quince\n": ("línea 2", "INT"),
            "1,Ana,1,15\n2,Bob,1\n": ("línea 2", "se esperaban 4"),
            "1,Ana,1,15\n2,Bob,,12\n": ("línea 2", "vacío"),
            "1,Ana,1,15\n1,Bob,1,12\n": ("alumnos_pkey", "(id)=(1)"),
        }
        for content, fragments in cases.items():
            with self.subTest(content=content):
                path = self.csv("bad.csv", content)
                message = self.error(f"COPY alumnos FROM '{path}'")
                for fragment in fragments:
                    self.assertIn(fragment, message)
                self.assertEqual(self.count("alumnos"), 0)

    def test_missing_file_and_relative_paths(self):
        self.assertIn("no existe", self.error("COPY alumnos FROM 'no_existe.csv'"))
        self.motor.statement_executor.base_dir = self.tmp.name
        self.csv("rel.csv", "1,Ana,1,15\n")
        self.assertEqual(self.run_sql("COPY alumnos FROM 'rel.csv'").mensaje, "COPY 1")

    def test_latin1_encoding_option_and_transaction_rollback(self):
        path = self.csv("latin.csv", "1,Muñoz,1,15\n", encoding="latin-1")
        self.assertIn("LATIN1", self.error(f"COPY alumnos FROM '{path}'"))
        self.run_sql(f"BEGIN; COPY alumnos FROM '{path}' WITH (ENCODING 'LATIN1')")
        self.assertEqual(self.run_sql("SELECT nombre FROM alumnos").filas, [("Muñoz",)])
        self.run_sql("ROLLBACK")
        self.assertEqual(self.count("alumnos"), 0)


class TestExplain(MotorTestCase):
    def setUp(self):
        super().setUp()
        self.run_sql("CREATE TABLE alumnos (id INT PRIMARY KEY, nombre VARCHAR(20), carrera_id INT, nota INT)")
        values = ", ".join(f"({i}, 'n{i}', {i % 5 + 1}, {i % 21})" for i in range(1, 501))
        self.run_sql(f"INSERT INTO alumnos VALUES {values}")
        self.run_sql("CREATE TABLE carreras (cid INT PRIMARY KEY, cnombre VARCHAR(10)) USING BTREE")
        self.run_sql("INSERT INTO carreras VALUES (1,'a'),(2,'b'),(3,'c'),(4,'d'),(5,'e')")

    def plan(self, sql):
        return self.run_sql(sql).plan

    def test_explain_matches_postgres_layout(self):
        plan = self.plan("EXPLAIN SELECT * FROM alumnos WHERE nota >= 14 ORDER BY id")
        # Sort es bloqueante: su costo de arranque es su costo total (>= el del hijo).
        startup, total = map(float, re.match(r"^Sort  \(cost=([0-9.]+)\.\.([0-9.]+) rows=\d+\)$", plan[0]).groups())
        self.assertEqual(plan[1], "  Sort Key: id")
        child = re.match(r"^  ->  Seq Scan on alumnos  \(cost=0\.00\.\.([0-9.]+) rows=\d+\)$", plan[2])
        self.assertEqual(startup, total)
        self.assertGreaterEqual(startup, float(child.group(1)))
        self.assertEqual(plan[3], "        Filter: (nota >= 14)")
        self.assertEqual(len(plan), 4)

    def test_blocking_operators_and_group_estimates(self):
        plan = self.plan("EXPLAIN SELECT carrera_id, COUNT(*) FROM alumnos GROUP BY carrera_id")
        startup, total, rows = re.match(r"^HashAggregate  \(cost=([0-9.]+)\.\.([0-9.]+) rows=(\d+)\)$",
                                        plan[0]).groups()
        self.assertEqual(startup, total)
        # Estimación con los valores distintos reales de la columna (estadísticas tras el INSERT).
        distinct = len({i % 5 + 1 for i in range(1, 501)})
        self.assertEqual(int(rows), distinct)

    def test_explain_shows_joins_aggregates_and_limits(self):
        plan = "\n".join(self.plan(
            "EXPLAIN SELECT c.cnombre, COUNT(*) AS n FROM alumnos a JOIN carreras c ON a.carrera_id = c.cid "
            "GROUP BY c.cnombre HAVING COUNT(*) > 10 ORDER BY n DESC LIMIT 3"))
        for fragment in ("Limit", "->  Sort", "Sort Key: count(*) DESC", "->  HashAggregate",
                         "Group Key: c.cnombre", "Filter: (count(*) > 10)", "Hash Cond: (a.carrera_id = c.cid)",
                         "Seq Scan on alumnos a", "->  Hash"):
            self.assertIn(fragment, plan)

    def test_explain_does_not_execute_but_analyze_does(self):
        plan = self.plan("EXPLAIN DELETE FROM alumnos WHERE nota = 0")
        self.assertTrue(plan[0].startswith("Delete on alumnos"))
        self.assertEqual(self.count("alumnos"), 500)
        victims = sum(1 for i in range(1, 501) if i % 21 == 0)
        plan = self.plan("EXPLAIN ANALYZE DELETE FROM alumnos WHERE nota = 0")
        self.assertEqual(self.count("alumnos"), 500 - victims)
        scan = next(line for line in plan if "Seq Scan" in line)
        self.assertIn(f"rows={victims} loops=1", scan)

    def test_analyze_reports_actual_rows_and_timings(self):
        plan = self.plan("EXPLAIN ANALYZE SELECT * FROM alumnos WHERE nota >= 14 ORDER BY id")
        expected = sum(1 for i in range(1, 501) if i % 21 >= 14)
        self.assertRegex(plan[0], rf"\(actual time=[0-9.]+\.\.[0-9.]+ rows={expected} loops=1\)$")
        self.assertIn("  Sort Method: in-memory", plan)
        self.assertIn(f"        Rows Removed by Filter: {500 - expected}", plan)
        self.assertTrue(re.match(r"^Planning Time: [0-9.]+ ms$", plan[-2]))
        self.assertTrue(re.match(r"^Execution Time: [0-9.]+ ms$", plan[-1]))

    def test_sequential_tables_use_binary_search(self):
        self.run_sql("CREATE TABLE seq (id INT PRIMARY KEY, v INT) USING SEQUENTIAL")
        self.run_sql("INSERT INTO seq VALUES " + ", ".join(f"({i}, {i % 7})" for i in range(2000, 0, -1)))
        plan = self.plan("EXPLAIN SELECT * FROM seq WHERE id BETWEEN 10 AND 12")
        self.assertTrue(plan[0].startswith("Index Scan using seq_pkey on seq"))
        self.assertEqual(plan[1], "  Index Cond: ((id >= 10) AND (id <= 12))")
        self.assertEqual(self.run_sql("SELECT id FROM seq WHERE id BETWEEN 10 AND 12").filas, [(10,), (11,), (12,)])
        self.assertTrue(self.plan("EXPLAIN SELECT * FROM seq WHERE v = 3")[0].startswith("Seq Scan on seq"))

    def test_clustered_order_and_range_use_the_index(self):
        plan = self.plan("EXPLAIN ANALYZE SELECT cid FROM carreras ORDER BY cid DESC")
        self.assertTrue(plan[0].startswith("Index Scan Backward using carreras_pkey on carreras"))
        self.assertIn("rows=5 loops=1", plan[0])
        self.assertNotIn("Sort", "\n".join(plan))


if __name__ == "__main__":
    unittest.main()
