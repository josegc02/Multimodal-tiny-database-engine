import csv
import os
import tempfile
import unittest
from unittest.mock import patch

from engine.query.errors import SQLSemanticError
from engine.query.logical_plan import LogicalPlanner
from engine.query.parser import parse
from frontend.csv_sql import sql_para_csv
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


class TextRowsTestCase(TextSQLTestCase):
    ROWS = [(1, 2001, "gato gato gato negro", "a", "uno"),
            (2, 2005, "gato blanco y perro", "b", "dos"),
            (3, 2010, "perro negro", "c", "tres"),
            (4, 2015, "raton de campo", "d", "cuatro"),
            (5, 2020, "gato en el tejado con un raton", "e", "cinco"),
            (6, 2025, "ave marina", "f", "seis")]

    def setUp(self):
        super().setUp()
        self.fill()

    def fill(self):
        values = ", ".join(str(row) for row in self.ROWS)
        self.execute(f"INSERT INTO docs VALUES {values}")

    def index(self):
        return self.motor.catalog.table("docs").indexes["contenido"].index

    def rows(self, sql):
        return self.execute(sql).filas

    def ranked(self, rank, query, count=100):
        storage = self.motor.catalog.table("docs").storage
        return [(storage.get(rid)["id"], score) for rid, score in rank(query, count)]


class TestExecution(TextRowsTestCase):
    def test_examples_of_the_project_statement(self):
        expected = self.ranked(self.index().rank_tfidf, "gato", 2)
        found = self.rows("SELECT id FROM docs WHERE MATCH(contenido, 'gato') USING TF_IDF LIMIT 2")
        self.assertEqual(found, [(doc_id,) for doc_id, _ in expected])
        expected = self.ranked(self.index().rank_bm25, "gato negro")
        found = self.rows("SELECT id, SCORE() as relevancia FROM docs "
                          "WHERE MATCH(contenido, 'gato negro') USING BM25 ORDER BY relevancia DESC")
        self.assertEqual(found, expected)
        columns = self.execute("SELECT *, SCORE() as relevancia FROM docs "
                               "WHERE MATCH(contenido, 'gato') USING BM25").columnas
        self.assertEqual(columns, ["id", "anio", "contenido", "otro", "titulo", "relevancia"])

    def test_limit_without_order_by_returns_the_top_k(self):
        for technique, rank in (("TF_IDF", self.index().rank_tfidf), ("BM25", self.index().rank_bm25)):
            with self.subTest(technique=technique):
                everything = self.ranked(rank, "gato raton")
                found = self.rows(f"SELECT id, SCORE() FROM docs WHERE MATCH(contenido, 'gato raton') "
                                  f"USING {technique} LIMIT 2")
                self.assertEqual(found, everything[:2])
                found = self.rows(f"SELECT id, SCORE() FROM docs WHERE MATCH(contenido, 'gato raton') "
                                  f"USING {technique} LIMIT 2 OFFSET 1")
                self.assertEqual(found, everything[1:3])

    def test_other_filters_do_not_lose_rows_of_the_top_k(self):
        everything = self.ranked(self.index().rank_bm25, "gato")
        recent = [row for row in everything if row[0] != 1]
        found = self.rows("SELECT id, SCORE() FROM docs WHERE MATCH(contenido, 'gato') USING BM25 "
                          "AND anio > 2001 LIMIT 2")
        self.assertEqual(found, recent[:2])

    def test_order_by_another_column_returns_only_matches(self):
        self.execute("CREATE INDEX docs_anio ON docs (anio) USING BTREE")
        found = self.rows("SELECT id FROM docs WHERE MATCH(contenido, 'gato') USING BM25 ORDER BY anio DESC LIMIT 2")
        self.assertEqual(found, [(5,), (2,)])
        found = self.rows("SELECT anio, COUNT(*) FROM docs WHERE MATCH(contenido, 'perro') USING BM25 "
                          "GROUP BY anio ORDER BY anio")
        self.assertEqual(found, [(2005, 1), (2010, 1)])

    def test_order_by_score_ascending(self):
        expected = self.ranked(self.index().rank_bm25, "gato")
        found = self.rows("SELECT id, SCORE() AS s FROM docs WHERE MATCH(contenido, 'gato') USING BM25 ORDER BY s ASC")
        self.assertEqual(sorted(found), sorted(expected))
        self.assertEqual([score for _, score in found], sorted(score for _, score in expected))

    def test_score_can_be_used_in_conditions_and_expressions(self):
        (_, best), *_ = self.ranked(self.index().rank_bm25, "gato")
        found = self.rows(f"SELECT id FROM docs WHERE MATCH(contenido, 'gato') USING BM25 AND SCORE() >= {best!r}")
        self.assertEqual(len(found), 1)
        doubled = self.rows("SELECT SCORE() * 2 FROM docs WHERE MATCH(contenido, 'gato') USING BM25 LIMIT 1")
        self.assertAlmostEqual(doubled[0][0], 2 * best)

    def test_aggregates_count_every_match(self):
        count = self.rows("SELECT COUNT(*) FROM docs WHERE MATCH(contenido, 'gato') USING BM25 LIMIT 1")
        self.assertEqual(count, [(3,)])

    def test_query_without_results(self):
        for query in ("inexistente", "", "de la"):
            with self.subTest(query=query):
                self.assertEqual(self.rows(f"SELECT id FROM docs WHERE MATCH(contenido, '{query}') USING BM25"), [])

    def test_results_follow_inserts_and_deletes(self):
        self.execute("INSERT INTO docs VALUES (7, 2026, 'gato gato gato gato', 'g', 'siete')")
        self.execute("DELETE FROM docs WHERE id = 1")
        expected = self.ranked(self.index().rank_bm25, "gato")
        found = self.rows("SELECT id, SCORE() FROM docs WHERE MATCH(contenido, 'gato') USING BM25")
        self.assertEqual(found, expected)
        self.assertEqual(found[0][0], 7)
        self.assertNotIn(1, [doc_id for doc_id, _ in found])


class TestExplain(TextRowsTestCase):
    def test_top_k(self):
        plan = self.execute("EXPLAIN SELECT * FROM docs WHERE MATCH(contenido, 'gato') USING TF_IDF LIMIT 2").plan
        text = "\n".join(plan)
        self.assertIn("Text Search using docs_contenido on docs", text)
        self.assertIn("Text Cond: match(contenido, 'gato')", text)
        self.assertIn("Ranking: TF-IDF (cosine); Top-k: 2", text)

    def test_explain_without_top_k(self):
        plan = "\n".join(self.execute("EXPLAIN SELECT id FROM docs WHERE MATCH(contenido, 'gato') USING BM25 "
                                      "AND anio > 2000 LIMIT 2").plan)
        self.assertIn("Ranking: BM25; All matches", plan)
        self.assertIn("Filter: (anio > 2000)", plan)

    def test_explain_estimates_rows_from_the_terms(self):
        plan = self.execute("EXPLAIN SELECT id FROM docs WHERE MATCH(contenido, 'gato') USING BM25").plan
        self.assertIn("rows=3", plan[0])
        self.assertEqual(self.index().stats.postings_read, 0)

    def test_analyze_reports_the_postings_read(self):
        self.index().reset_stats()
        plan = "\n".join(self.execute("EXPLAIN ANALYZE SELECT id FROM docs "
                                      "WHERE MATCH(contenido, 'gato negro') USING BM25 LIMIT 2").plan)
        self.assertIn(f"Postings Read: {self.index().stats.postings_read};", plan)
        self.assertIn("Postings Read: 5;", plan)
        self.assertIn("Index Pages Read:", plan)

    def test_explain_shows_score_in_sort_and_filter(self):
        plan = "\n".join(self.execute("EXPLAIN SELECT id FROM docs WHERE MATCH(contenido, 'gato') USING BM25 "
                                      "AND SCORE() > 0.1 ORDER BY SCORE()").plan)
        self.assertIn("Sort Key: score()", plan)
        self.assertIn("Filter: (score() > 0.1)", plan)


class TestIntegration(TextSQLTestCase):
    def test_rollback_removes_the_document_from_the_results(self):
        self.execute("INSERT INTO docs VALUES (1, 2001, 'gato negro', 'a', 'uno')")
        self.motor.ejecutar("BEGIN TRANSACTION")
        self.execute("INSERT INTO docs VALUES (2, 2002, 'gato pardo', 'b', 'dos')")
        self.execute("DELETE FROM docs WHERE id = 1")
        self.motor.ejecutar("ROLLBACK")
        found = self.execute("SELECT id FROM docs WHERE MATCH(contenido, 'gato') USING BM25").filas
        self.assertEqual(found, [(1,)])

    def test_table_with_a_point_column(self):
        self.execute("CREATE TABLE lugares (id INT, ubicacion POINT, resena TEXT)")
        self.execute("CREATE INDEX lugares_resena ON lugares (resena) USING SPIMI")
        self.execute("INSERT INTO lugares VALUES (1, POINT(-12.1, -77.0), 'buen cafe'), "
                     "(2, POINT(-12.2, -77.1), 'mal servicio')")
        result = self.execute("SELECT id FROM lugares WHERE MATCH(resena, 'cafe') USING TF_IDF")
        self.assertEqual(result.filas, [(1,)])

    def test_copy_then_index_then_search_in_english(self):
        path = os.path.join(self.temp_dir.name, "articulos.csv")
        documents = [f"machine learning model number {number} " + "with many words " * 300 for number in range(20)]
        documents += ["databases and running queries " * 300]
        with open(path, "w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["id", "texto"])
            writer.writerows(enumerate(documents))
        script = sql_para_csv(path, self.motor.catalog.tables)
        self.assertIn("texto TEXT", script)
        self.execute(script)
        self.execute("CREATE INDEX articulos_texto ON articulos (texto) USING SPIMI WITH (LANGUAGE = 'en')")
        found = self.execute("SELECT id, texto, SCORE() AS relevancia FROM articulos "
                             "WHERE MATCH(texto, 'database query') USING BM25 ORDER BY relevancia DESC LIMIT 5").filas
        self.assertEqual([(row[0], row[1]) for row in found], [(20, documents[20])])


class TestExecutionInEveryStorage(TextSQLTestCase):
    def test_every_storage_returns_the_same_ranking(self):
        results = []
        for method in ("HEAP", "SEQUENTIAL", "BTREE"):
            table = f"t_{method.lower()}"
            self.execute(f"CREATE TABLE {table} (id INT PRIMARY KEY, contenido TEXT) USING {method}")
            self.execute(f"CREATE INDEX i_{table} ON {table} (contenido) USING SPIMI")
            self.execute(f"INSERT INTO {table} VALUES (2, 'gato gato pardo'), (1, 'gato'), (3, 'perro')")
            self.execute(f"DELETE FROM {table} WHERE id = 3")
            self.execute(f"INSERT INTO {table} VALUES (4, 'perro gato')")
            results.append(sorted(self.execute(f"SELECT id, SCORE() FROM {table} "
                                               "WHERE MATCH(contenido, 'gato') USING BM25").filas))
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0], results[2])
        self.assertEqual([doc_id for doc_id, _ in results[0]], [1, 2, 4])


if __name__ == "__main__":
    unittest.main()
