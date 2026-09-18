"""Decisiones por costo verificadas contra las rutas de ejecución reales."""

from unittest.mock import patch

from engine.indexes import ExtendibleHash
from engine.query import Catalog, SQLExecutor
from engine.query.external_algorithms import ExecutionStats
from engine.query.planner import IndexInfo, TableStats
from tests.query.test_sql_execution import SQLTestCase


def physical_nodes(explanation):
    if "physical" in explanation:
        yield explanation["physical"]
    for child in explanation["children"]:
        yield from physical_nodes(child)


class OrderedIndex:
    """Contrato de índice ordenado; el B+ del proyecto aún está incompleto."""
    def __init__(self):
        self.hash = ExtendibleHash()

    def bulk_load_from_storage(self, storage, column, replace=True):
        self.hash.bulk_load_from_storage(storage, column, replace=replace)
        self.rids = [rid for rid, _ in sorted(storage.scan(), key=lambda item: item[1][column])]

    def search(self, value):
        return self.hash.search(value)

    def iter_ordered(self, reverse=False):
        return iter(self.rids[::-1] if reverse else self.rids)


class TestSQLCostOptimizer(SQLTestCase):
    def test_equality_cost_and_stale_index(self):
        storage, catalog, executor = self.database(indexed=True)
        binding = catalog.table("productos")
        sql = "SELECT id FROM productos WHERE id=2"
        index = binding.indexes["id"].index
        # Tabla pequeña: un scan cuesta menos que la búsqueda aleatoria.
        with patch.object(index, "search", side_effect=AssertionError("Índice caro")):
            self.assertEqual(list(executor.execute(sql)), [{"id": 2}])
        self.assertEqual(next(physical_nodes(executor.explain(sql)))["algorithm"], "sequential_scan")
        binding.statistics = TableStats(1000, 100, {"id": 1000})
        with patch.object(storage, "scan", side_effect=AssertionError("explain no lee datos")):
            selected = next(physical_nodes(executor.explain(sql)))
            self.assertEqual(selected["algorithm"], "index_scan")
            self.assertEqual(selected["estimated_io"], 5)
            self.assertEqual(list(executor.execute(sql)), [{"id": 2}])
        binding.invalidate_indexes()
        self.assertEqual(next(physical_nodes(executor.explain(sql)))["algorithm"], "sequential_scan")
        self.assertEqual(list(executor.execute(sql)), [{"id": 2}])

    def test_join_switches_between_index_and_external(self):
        for kind in ("heap", "sequential"):
            with self.subTest(kind=kind):
                left, _, _ = self.database(kind)
                right, catalog, executor = self.database(kind, indexed=True)
                catalog.register_table("izquierda", left)
                binding = catalog.table("productos")
                sql = ("SELECT a.id AS id FROM izquierda a JOIN productos b "
                       "ON a.id=b.id AND b.precio > 10 ORDER BY id")
                expected = [{"id": 1}, {"id": 2}, {"id": 3}]
                binding.statistics = TableStats(10000, 1000, {"id": 10000})
                stats = ExecutionStats()
                with patch.object(right, "scan", side_effect=AssertionError("JOIN debe usar índice")):
                    self.assertEqual(list(executor.execute(sql, stats=stats)), expected)
                self.assertEqual(stats.index_probes, 4)
                self.assertIn("index_nested_loop_join", [p["algorithm"] for p in physical_nodes(executor.explain(sql))])
                binding.statistics = TableStats(10000, 1000, {"id": 1})
                with patch.object(binding.indexes["id"].index, "search", side_effect=AssertionError("JOIN externo")):
                    self.assertEqual(list(executor.execute(sql)), expected)
                self.assertIn("external_hash_join", [p["algorithm"] for p in physical_nodes(executor.explain(sql))])
                self.assertEqual(list(self.spill.iterdir()), [])

    def test_order_and_group_use_ordered_index_or_external_by_cost(self):
        storage, _, _ = self.database()
        index = OrderedIndex()
        catalog = Catalog()
        binding = catalog.register_table("productos", storage, {
            "categoria": IndexInfo("category_order", "categoria", index, ordered=True, clustered=True)
        })
        executor = SQLExecutor(catalog, self.config)
        queries = [
            ("SELECT categoria FROM productos WHERE precio > 10 ORDER BY categoria DESC",
             [{"categoria": "tech"}, {"categoria": "tech"}, {"categoria": "libros"}], "index_order_scan"),
            ("SELECT categoria, COUNT(*) AS n FROM productos WHERE precio > 10 GROUP BY categoria",
             [{"categoria": "libros", "n": 1}, {"categoria": "tech", "n": 2}], "index_group_by"),
        ]
        for sql, expected, algorithm in queries:
            with self.subTest(algorithm=algorithm):
                self.assertIn(algorithm, [p["algorithm"] for p in physical_nodes(executor.explain(sql))])
                with patch.object(storage, "scan", side_effect=AssertionError("Recorrido ordenado")):
                    self.assertEqual(list(executor.execute(sql)), expected)
        # Mantener el índice válido, pero elevar el costo de acceso.
        from dataclasses import replace
        binding.indexes["categoria"].metadata = replace(binding.indexes["categoria"].metadata, lookup_pages=10000)
        for sql, expected, _ in queries:
            with patch.object(index, "iter_ordered", side_effect=AssertionError("Índice caro")):
                result = list(executor.execute(sql))
            self.assertEqual(sorted(result, key=str), sorted(expected, key=str))
        self.assertEqual(list(self.spill.iterdir()), [])

    def test_expressions_fall_back_and_writes_refresh_statistics(self):
        _, catalog, executor = self.database(indexed=True)
        for sql in ("SELECT id FROM productos ORDER BY precio + 1",
                    "SELECT id + 1 AS n, COUNT(*) FROM productos GROUP BY id + 1"):
            algorithms = [p["algorithm"] for p in physical_nodes(executor.explain(sql))]
            self.assertTrue(any(a in ("external_sort", "external_hash_group_by") for a in algorithms))
            self.assertEqual(len(list(executor.execute(sql))), 4)
        executor.execute("DELETE FROM productos WHERE id=1")
        self.assertEqual(catalog.table("productos").statistics.rows, 3)
        executor.execute("INSERT INTO productos VALUES (5, 'Nuevo', 'tech', 10)")
        self.assertEqual(catalog.table("productos").statistics.rows, 4)
