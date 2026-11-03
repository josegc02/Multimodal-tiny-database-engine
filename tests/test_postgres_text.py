import os
import tempfile
import unittest
from pathlib import Path

from benchmarks.generate_text_datasets import generate
from postgres_text.client import analyze, build_index, connect, initialize, load_csv
from postgres_text.queries import explain, query_expression, ranked_statement, search, search_tsquery
from postgres_text.schema import table_name
from postgres_text.verify import verify


class TestTextQueryContract(unittest.TestCase):
    def test_literal_or_words(self):
        self.assertEqual(query_expression("inflación precios alimentos"), "'inflación' | 'precios' | 'alimentos'")
        self.assertEqual(query_expression("GATO gato & !perro:*"), "'gato' | 'perro'")
        self.assertEqual(query_expression("don't"), "'don''t'")
        self.assertEqual(query_expression(" "), "")

    def test_invalid_size_cannot_be_sql_identifier(self):
        for value in (-1, 0, True, "1000; DROP SCHEMA texto CASCADE"):
            with self.assertRaises(ValueError):
                table_name(value)


@unittest.skipUnless(os.environ.get("TEXT_POSTGRES_TEST_DSN"), "requiere TEXT_POSTGRES_TEST_DSN")
class TestPostgresText(unittest.TestCase):
    def setUp(self):
        self.connection = connect(os.environ["TEXT_POSTGRES_TEST_DSN"])
        self.addCleanup(self.connection.close)
        self.connection.execute("BEGIN")
        self.addCleanup(self.connection.execute, "ROLLBACK")
        initialize(self.connection)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "data"
        generate(self.root, sizes=(24,))
        self.csv = self.root / "noticias_24.csv"

    def load(self):
        return load_csv(self.connection, self.csv, 24)

    def test_exact_copy_and_generated_language(self):
        self.load()
        self.assertTrue(verify(self.connection, self.csv, 24)["exact_match"])
        self.connection.execute("SET LOCAL default_text_search_config = 'english'")
        self.connection.execute("UPDATE texto.noticias_24 SET contenido='vacunas enfermedades' WHERE id=1")
        equal = self.connection.execute("SELECT full_text=to_tsvector('spanish',contenido) "
                                        "FROM texto.noticias_24 WHERE id=1").fetchone()[0]
        self.assertTrue(equal)
        with self.assertRaisesRegex(ValueError, "Contenido diferente"):
            verify(self.connection, self.csv, 24)

    def test_invalid_size_does_not_create_table(self):
        with self.assertRaises(ValueError):
            load_csv(self.connection, self.csv, 23)
        self.assertIsNone(self.connection.execute("SELECT to_regclass('texto.noticias_23')").fetchone()[0])

    def test_duplicate_load_preserves_rows(self):
        import psycopg

        self.load()
        with self.assertRaises(psycopg.errors.DuplicateTable):
            self.load()
        self.assertTrue(verify(self.connection, self.csv, 24)["exact_match"])

    def test_failure_after_copy_rolls_back_table(self):
        import psycopg

        self.connection.execute("INSERT INTO texto.dataset_loads VALUES (24,'occupied','x','spanish',DEFAULT)")
        with self.assertRaises(psycopg.errors.UniqueViolation):
            self.load()
        self.assertIsNone(self.connection.execute("SELECT to_regclass('texto.noticias_24')").fetchone()[0])

    def test_ranked_results_match_scan_and_native_query(self):
        self.load()
        before = search(self.connection, 24, "inflación precios alimentos", 10)
        native = search_tsquery(self.connection, 24, "inflación | precios | alimentos", 10)
        self.assertEqual(before, native)
        self.assertTrue(before)
        build_index(self.connection, 24)
        analyze(self.connection, 24)
        after = search(self.connection, 24, "inflación precios alimentos", 10)
        self.assertEqual(before, after)
        self.assertEqual(after, sorted(after, key=lambda row: (-row[1], row[0])))
        self.assertTrue(all(score > 0 for _, score in after))

    def test_empty_unknown_stopwords_and_hostile_text(self):
        self.load()
        for text in ("", "!!!", "de la el", "zzzinexistentexyz"):
            self.assertEqual(search(self.connection, 24, text), [])
        for text in ("don't", "gato'); DROP TABLE texto.noticias_24; --", "gato & !perro:*", "niño\\niña"):
            search(self.connection, 24, text)
        self.assertEqual(search(self.connection, 24, "inflación", 0), [])
        self.assertTrue(verify(self.connection, self.csv, 24)["exact_match"])
        for k in (-1, 1.5, True):
            with self.assertRaises(ValueError):
                ranked_statement(24, "gato", k)

    def test_index_is_available_and_used_when_requested_locally(self):
        self.load()
        build_index(self.connection, 24)
        analyze(self.connection, 24)
        natural = explain(self.connection, 24, "inflación")
        self.assertIn("Plan", natural[0])
        # Solo diagnóstico: en 24 filas PostgreSQL puede preferir Seq Scan.
        self.connection.execute("SET LOCAL enable_seqscan = off")
        plan = explain(self.connection, 24, "inflación")

        def nodes(node):
            yield node
            for child in node.get("Plans", []):
                yield from nodes(child)

        names = [node.get("Index Name") for node in nodes(plan[0]["Plan"])]
        self.assertIn("noticias_24_gin", names)
