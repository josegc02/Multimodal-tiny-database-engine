"""Ejemplos de la sección 2.1.3 y su integración con storage/índices.

El enunciado da cuatro plantillas, no SQL literal ejecutable: aquí se instancian
sobre productos. La segunda plantilla se prueba con ORDER BY y con GROUP BY.
"""

from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from engine.indexes import ExtendibleHash
from engine.query import (Catalog, LogicalPlanner, SQLExecutor, SQLSemanticError,
                          SQLExecutionError, parse)
from engine.query.external_algorithms import BufferConfig, ExecutionStats
from engine.query.planner import TableStats
from engine.storage.heap_file import HeapFile
from engine.storage.sequential_file import SequentialFile

SCHEMA = [("id", "int"), ("nombre", "str", 12), ("categoria", "str", 8), ("precio", "float")]
DATA = [(1, "Mouse", "tech", 20.0), (2, "Libro", "libros", 15.0),
        (3, "Teclado", "tech", 45.0), (4, "Cuaderno", "libros", 5.0)]


class SQLTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.spill = Path(self.tmp.name) / "spill"
        self.spill.mkdir()
        self.config = BufferConfig(3, 2, temp_dir=str(self.spill))
        self.number = 0

    def database(self, kind="heap", *, indexed=False, empty=False):
        self.number += 1
        path = str(Path(self.tmp.name) / str(self.number))
        if kind == "heap":
            storage = HeapFile(path + ".heap", SCHEMA, page_size=128)
        else:
            storage = SequentialFile(path + ".main", path + ".aux", SCHEMA, "id", page_size=128)
        self.addCleanup(storage.close)
        if not empty:
            for values in DATA:
                storage.insert(dict(zip(storage.schema.fields, values)))
        catalog = Catalog()
        indexes = {"id": ExtendibleHash(), "categoria": ExtendibleHash()} if indexed else None
        catalog.register_table("productos", storage, indexes)
        return storage, catalog, SQLExecutor(catalog, self.config)


class TestEnunciadoExamples(SQLTestCase):
    def test_ejemplo_1_select_where(self):
        for kind in ("heap", "sequential"):
            with self.subTest(storage=kind):
                _, _, executor = self.database(kind, indexed=True)
                result = list(executor.execute("SELECT * FROM productos WHERE id = 3"))
                self.assertEqual(result, [{"id": 3, "nombre": "Teclado", "categoria": "tech", "precio": 45.0}])

    def test_ejemplo_2_order_by_y_group_by(self):
        for kind in ("heap", "sequential"):
            with self.subTest(storage=kind):
                _, _, executor = self.database(kind)
                ordered = list(executor.execute("SELECT * FROM productos ORDER BY precio DESC"))
                self.assertEqual([row["id"] for row in ordered], [3, 1, 2, 4])
                grouped = list(executor.execute("SELECT categoria, COUNT(*) AS cantidad FROM productos GROUP BY categoria ORDER BY categoria"))
                self.assertEqual(grouped, [{"categoria": "libros", "cantidad": 2}, {"categoria": "tech", "cantidad": 2}])

    def test_ejemplo_3_insert_into_values(self):
        for kind in ("heap", "sequential"):
            with self.subTest(storage=kind):
                storage, catalog, executor = self.database(kind, indexed=True)
                result = list(executor.execute("INSERT INTO productos VALUES (0, 'Monitor', 'tech', 100.0)"))
                self.assertEqual(result, [{"affected_rows": 1}])
                for rid, row in storage.scan():
                    self.assertIn(rid, catalog.table("productos").indexes["id"].index.search(row["id"]))
                self.assertEqual(list(executor.execute("SELECT nombre FROM productos WHERE id = 0")), [{"nombre": "Monitor"}])

    def test_ejemplo_4_delete_where(self):
        for kind in ("heap", "sequential"):
            with self.subTest(storage=kind):
                storage, catalog, executor = self.database(kind, indexed=True)
                self.assertEqual(list(executor.execute("DELETE FROM productos WHERE precio < 20")), [{"affected_rows": 2}])
                self.assertEqual([row["id"] for _, row in storage.scan()], [1, 3])
                self.assertEqual(list(executor.execute("SELECT * FROM productos WHERE id = 2")), [])
                self.assertEqual(catalog.table("productos").indexes["id"].index.search(2), [])


class TestLogicalPlanner(SQLTestCase):
    def test_plan_pipeline_order(self):
        _, catalog, _ = self.database()
        plan = LogicalPlanner(catalog).plan(parse("""
            SELECT categoria, SUM(precio) AS total FROM productos WHERE precio > 0
            GROUP BY categoria HAVING SUM(precio) > 10 ORDER BY total DESC LIMIT 2
        """))
        operations = []
        current = plan
        while True:
            operations.append(current.operation)
            if not current.children:
                break
            current = current.children[0]
        self.assertEqual(operations, ["Limit", "Project", "Sort", "Filter", "Aggregate", "Filter", "Scan"])
        self.assertEqual(plan.to_dict()["operation"], "Limit")

    def test_semantic_errors_are_caught_even_on_empty_table(self):
        _, catalog, _ = self.database(empty=True)
        planner = LogicalPlanner(catalog)
        queries = [
            "SELECT id FROM inexistente", "SELECT inexistente FROM productos",
            "SELECT productos.id FROM productos p", "SELECT id, id FROM productos",
            "SELECT id, COUNT(*) FROM productos", "SELECT * FROM productos GROUP BY categoria",
            "SELECT id FROM productos WHERE COUNT(*) > 0",
            "SELECT id FROM productos GROUP BY SUM(precio)",
            "SELECT id FROM productos ORDER BY 2", "SELECT COUNT(DISTINCT id) FROM productos",
            "SELECT a.id FROM productos a JOIN productos b ON a.id > b.id",
            "SELECT id FROM productos a JOIN productos b ON a.id=b.id", "BEGIN",
        ]
        for sql in queries:
            with self.subTest(sql=sql), self.assertRaises(SQLSemanticError):
                planner.plan(parse(sql))


class TestSQLStorageIntegration(SQLTestCase):
    def test_real_index_is_used_and_or_does_not_lose_rows(self):
        storage, catalog, executor = self.database(indexed=True)
        index = catalog.table("productos").indexes["id"].index
        # Simular una tabla grande y selectiva: el índice debe ganar por costo.
        catalog.table("productos").statistics = TableStats(1000, 100, {"id": 1000})
        stats = ExecutionStats()
        with patch.object(storage, "scan", side_effect=AssertionError("No debería hacer scan")), patch.object(index, "search", wraps=index.search) as search:
            self.assertEqual(list(executor.execute("SELECT nombre FROM productos WHERE 2=id AND precio > 10", stats=stats)), [{"nombre": "Libro"}])
            search.assert_called_once_with(2)
        self.assertEqual(stats.index_probes, 1)
        self.assertEqual(list(executor.execute("SELECT id FROM productos WHERE id=1 OR id=4 ORDER BY id")), [{"id": 1}, {"id": 4}])

    def test_result_queries_against_sqlite(self):
        _, _, executor = self.database()
        db = sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        db.execute("CREATE TABLE productos(id INTEGER, nombre TEXT, categoria TEXT, precio REAL)")
        db.executemany("INSERT INTO productos VALUES(?,?,?,?)", DATA)
        queries = [
            "SELECT id, nombre FROM productos WHERE precio BETWEEN 10 AND 50 AND nombre NOT LIKE 'M%' ORDER BY precio DESC",
            "SELECT id FROM productos WHERE NOT (id=1 OR id=2) ORDER BY id",
            "SELECT id FROM productos WHERE id NOT IN (1, NULL) ORDER BY id",
            "SELECT categoria, COUNT(*) AS n, SUM(precio) AS total, AVG(precio) AS media, MIN(precio) AS menor, MAX(precio) AS mayor FROM productos GROUP BY categoria HAVING SUM(precio)>10 ORDER BY total DESC",
            "SELECT DISTINCT categoria FROM productos ORDER BY categoria",
            "SELECT id, precio * 2 + 1 AS ajustado FROM productos ORDER BY ajustado DESC LIMIT 2 OFFSET 1",
            "SELECT a.id AS izquierda, b.id AS derecha FROM productos a JOIN productos b ON a.categoria=b.categoria WHERE a.id < b.id ORDER BY izquierda, derecha",
        ]
        for sql in queries:
            with self.subTest(sql=sql):
                cursor = db.execute(sql)
                expected = [dict(zip((col[0] for col in cursor.description), row)) for row in cursor.fetchall()]
                self.assertEqual(list(executor.execute(sql)), expected)

    def test_group_by_expression_and_empty_global_aggregate(self):
        _, _, executor = self.database()
        self.assertEqual(list(executor.execute("SELECT id % 2 AS paridad, COUNT(*) AS n FROM productos GROUP BY id % 2 ORDER BY paridad")),
                         [{"paridad": 0, "n": 2}, {"paridad": 1, "n": 2}])
        self.assertEqual(list(executor.execute("SELECT COUNT(*) AS n, SUM(precio) AS total FROM productos WHERE id < 0")),
                         [{"n": 0, "total": None}])

    def test_insert_validates_entire_batch_before_mutation(self):
        storage, _, executor = self.database(indexed=True)
        before = list(storage.scan())
        for sql in ["INSERT INTO productos VALUES (9,'ok','tech',10),(10,'bad','tech','no')",
                    "INSERT INTO productos (id) VALUES (9)",
                    "INSERT INTO productos VALUES (9,NULL,'tech',10)"]:
            with self.subTest(sql=sql), self.assertRaises(SQLSemanticError):
                executor.execute(sql)
            self.assertEqual(list(storage.scan()), before)

    def test_delete_evaluates_all_rows_before_mutation(self):
        storage, _, executor = self.database(indexed=True)
        before = list(storage.scan())
        with self.assertRaises(SQLExecutionError):
            executor.execute("DELETE FROM productos WHERE id=1 OR 1/(id-2)>0")
        self.assertEqual(list(storage.scan()), before)

    def test_failed_insert_leaves_index_invalid_and_scan_available(self):
        storage, catalog, executor = self.database(indexed=True)
        original = storage.insert
        calls = 0
        def fail_second(record):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("simular fallo de disco")
            return original(record)
        with patch.object(storage, "insert", side_effect=fail_second), self.assertRaises(OSError):
            executor.execute("INSERT INTO productos VALUES (9,'nueve','tech',9),(10,'diez','tech',10)")
        binding = catalog.table("productos")
        self.assertFalse(binding.indexes["id"].valid)
        self.assertEqual(list(executor.execute("SELECT id FROM productos WHERE id=9")), [{"id": 9}])
        binding.refresh_indexes()
        self.assertTrue(binding.indexes["id"].valid)

    def test_indexes_use_serialized_values_after_truncation(self):
        storage, catalog, executor = self.database(indexed=True)
        executor.execute("INSERT INTO productos VALUES (10,'abcdefghijklmno','technology',1)")
        self.assertEqual(list(executor.execute("SELECT nombre FROM productos WHERE categoria='technolo'")), [{"nombre": "abcdefghijkl"}])
        index = catalog.table("productos").indexes["categoria"].index
        self.assertEqual(len(index.search("technolo")), 1)

    def test_execute_prebuilt_plan_and_early_close_removes_temporaries(self):
        _, catalog, executor = self.database()
        plan = LogicalPlanner(catalog).plan(parse("SELECT * FROM productos ORDER BY precio"))
        result = executor.execute(plan)
        next(result)
        result.close()
        self.assertEqual(list(self.spill.iterdir()), [])
        self.assertEqual(list(executor.execute("SELECT id FROM productos LIMIT 0")), [])

    def test_preserves_unrelated_table_and_supports_custom_column_order(self):
        storage, catalog, executor = self.database(empty=True)
        executor.execute("INSERT INTO productos (precio,categoria,nombre,id) VALUES (10,'tech','x',1)")
        self.assertEqual(list(executor.execute("SELECT * FROM productos")), [{"id": 1, "nombre": "x", "categoria": "tech", "precio": 10.0}])
        self.assertEqual(list(executor.execute("DELETE FROM productos")), [{"affected_rows": 1}])
        self.assertEqual(list(storage.scan()), [])


if __name__ == "__main__":
    unittest.main()
