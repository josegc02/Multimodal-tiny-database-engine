import tempfile
import unittest
from unittest.mock import patch

from engine.query.errors import SQLSemanticError
from engine.query.logical_plan import LogicalPlanner
from engine.query.parser import parse
from frontend.motor import Motor


class TextSQLTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        patcher = patch("frontend.motor.DEMO_DIR", self.temp_dir.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.motor = Motor()
        self.addCleanup(self.motor.cerrar)
        self.execute("CREATE TABLE docs (id INT PRIMARY KEY, anio INT, contenido TEXT, otro TEXT, titulo VARCHAR(30))")
        self.execute("CREATE INDEX docs_contenido ON docs (contenido) USING SPIMI")

    def execute(self, sql):
        result = self.motor.ejecutar(sql)
        self.assertFalse(result.tiene_error, result.error)
        return result

    def plan(self, sql):
        return LogicalPlanner(self.motor.catalog).plan(parse(sql))


class TestPlanner(TextSQLTestCase):
    MATCH = "MATCH(contenido, 'gato') USING BM25"

    def scan(self, plan):
        while plan.operation != "Scan":
            plan = plan.children[0]
        return plan

    def operations(self, plan):
        return [plan.operation] + [name for child in plan.children for name in self.operations(child)]

    def text_k(self, tail, columns="*", where=""):
        return self.scan(self.plan(f"SELECT {columns} FROM docs WHERE {self.MATCH} {where} {tail}")).get("text_k")

    def test_match_goes_to_the_scan_and_leaves_the_where(self):
        plan = self.plan(f"SELECT * FROM docs WHERE {self.MATCH}")
        match = self.scan(plan).get("text_match")
        self.assertEqual((match.column.name, match.query, match.ranking), ("contenido", "gato", "bm25"))
        self.assertIsNone(self.scan(plan).get("predicate"))
        self.assertNotIn("Filter", self.operations(plan))

    def test_other_conditions_stay_in_the_where(self):
        for where in (f"{self.MATCH} AND anio > 2000", f"anio > 2000 AND {self.MATCH}"):
            with self.subTest(where=where):
                plan = self.plan(f"SELECT * FROM docs WHERE {where}")
                self.assertIsNotNone(self.scan(plan).get("text_match"))
                self.assertIn("Filter", self.operations(plan))

    def test_limit_is_pushed_only_when_it_cannot_lose_rows(self):
        self.assertEqual(self.text_k("LIMIT 10"), 10)
        self.assertEqual(self.text_k("LIMIT 10 OFFSET 5"), 15)
        self.assertEqual(self.text_k("ORDER BY relevancia DESC LIMIT 10", "*, SCORE() AS relevancia"), 10)
        self.assertEqual(self.text_k("ORDER BY SCORE() DESC LIMIT 10"), 10)
        for tail, columns, where in (("", "*", ""),
                                     ("OFFSET 5", "*", ""),
                                     ("LIMIT 10", "*", "AND anio > 2000"),
                                     ("ORDER BY anio LIMIT 10", "*", ""),
                                     ("ORDER BY SCORE() ASC LIMIT 10", "*", ""),
                                     ("ORDER BY SCORE() DESC, anio LIMIT 10", "*", ""),
                                     ("LIMIT 1", "COUNT(*)", ""),
                                     ("GROUP BY anio LIMIT 1", "anio", "")):
            with self.subTest(tail=tail, columns=columns, where=where):
                self.assertIsNone(self.text_k(tail, columns, where))

    def test_distinct_does_not_push_the_limit(self):
        plan = self.plan(f"SELECT DISTINCT anio FROM docs WHERE {self.MATCH} LIMIT 3")
        self.assertIsNone(self.scan(plan).get("text_k"))

    def test_order_by_score_needs_no_sort(self):
        plan = self.plan(f"SELECT *, SCORE() AS r FROM docs WHERE {self.MATCH} ORDER BY r DESC LIMIT 3")
        self.assertNotIn("Sort", self.operations(plan))
        plan = self.plan(f"SELECT * FROM docs WHERE {self.MATCH} ORDER BY SCORE() ASC")
        self.assertIn("Sort", self.operations(plan))

    def test_rejected_queries(self):
        self.execute("CREATE TABLE autores (id INT, nombre VARCHAR(20))")
        for sql in (f"SELECT * FROM docs WHERE {self.MATCH} OR anio > 2000",
                    f"SELECT * FROM docs WHERE NOT {self.MATCH}",
                    f"SELECT * FROM docs WHERE {self.MATCH} AND {self.MATCH}",
                    f"SELECT {self.MATCH} FROM docs",
                    f"SELECT * FROM docs ORDER BY {self.MATCH}",
                    f"SELECT * FROM docs JOIN autores ON docs.id = autores.id WHERE {self.MATCH}",
                    f"DELETE FROM docs WHERE {self.MATCH}",
                    "SELECT * FROM docs WHERE MATCH(otro, 'gato') USING BM25",
                    "SELECT * FROM docs WHERE MATCH(titulo, 'gato') USING BM25",
                    "SELECT * FROM docs WHERE MATCH(anio, 'gato') USING BM25",
                    "SELECT * FROM docs WHERE MATCH(nada, 'gato') USING BM25",
                    "SELECT SCORE() FROM docs",
                    "SELECT * FROM docs ORDER BY SCORE() DESC",
                    "DELETE FROM docs WHERE SCORE() > 1",
                    f"SELECT COUNT(*), SCORE() FROM docs WHERE {self.MATCH}",
                    f"SELECT MAX(SCORE()) FROM docs WHERE {self.MATCH}"):
            with self.subTest(sql=sql), self.assertRaises(SQLSemanticError):
                self.plan(sql)


if __name__ == "__main__":
    unittest.main()
