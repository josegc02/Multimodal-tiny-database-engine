"""Decisiones por costo verificadas contra las rutas de ejecución reales."""

from unittest.mock import patch

from engine.indexes import ExtendibleHash
from engine.query import Catalog, SQLExecutor
from engine.query.explain import PlanExplainer
from engine.query.external_algorithms import ExecutionStats
from engine.query.parser import parse
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
            # Descenso + entrada + una lectura aleatoria + CPU de la fila.
            self.assertAlmostEqual(selected["estimated_io"], 1 + 0.05 + 4 + 0.1)
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
        # Con pocas filas ordenar en memoria es más barato: se simula una tabla grande.
        binding.statistics = TableStats(1000, 100)
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

    def scan_costs(self, executor, sql):
        return [p["estimated_io"] for p in physical_nodes(executor.explain(sql))]

    def ordered_setup(self):
        storage, _, _ = self.database()
        index = OrderedIndex()
        catalog = Catalog()
        binding = catalog.register_table("productos", storage, {
            "precio": IndexInfo("productos_precio", "precio", index, ordered=True)
        })
        binding.statistics = TableStats(10000, 121, value_bounds={"precio": (1, 5000)})
        return SQLExecutor(catalog, self.config), index

    def test_limit_makes_the_ordered_index_cheaper_than_sorting(self):
        executor, _ = self.ordered_setup()
        algorithms = lambda sql: [p["algorithm"] for p in physical_nodes(executor.explain(sql))]
        self.assertIn("index_order_scan", algorithms("SELECT id FROM productos ORDER BY precio DESC NULLS FIRST LIMIT 10"))
        self.assertIn("index_order_scan", algorithms("SELECT id FROM productos ORDER BY precio DESC NULLS FIRST LIMIT 5 OFFSET 5"))
        # Sin LIMIT hay que traer las 10.000 filas y el costo depende del índice y del sort.
        unlimited = self.scan_costs(executor, "SELECT id FROM productos ORDER BY precio DESC NULLS FIRST")
        limited = self.scan_costs(executor, "SELECT id FROM productos ORDER BY precio DESC NULLS FIRST LIMIT 10")
        self.assertLess(limited[0], unlimited[0])

    def test_limit_stops_reading_records(self):
        executor, index = self.ordered_setup()
        storage = executor.catalog.table("productos").storage
        with patch.object(storage, "get", wraps=storage.get) as get:
            rows = list(executor.execute("SELECT id FROM productos ORDER BY precio DESC NULLS FIRST LIMIT 1"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(get.call_count, 1)

    def test_tiny_table_keeps_the_sequential_scan(self):
        executor, _ = self.ordered_setup()
        executor.catalog.table("productos").statistics = TableStats(3, 1, value_bounds={"precio": (1, 5000)})
        for sql in ("SELECT id FROM productos WHERE precio = 10", "SELECT id FROM productos ORDER BY precio"):
            algorithms = [p["algorithm"] for p in physical_nodes(executor.explain(sql))]
            self.assertFalse([a for a in algorithms if a.startswith("index")], sql)

    def test_explain_counts_the_table_read_once(self):
        _, catalog, executor = self.database()
        stats = catalog.table("productos").statistics
        plan = executor.planner.plan(parse("SELECT COUNT(*) FROM productos"))
        root = PlanExplainer(catalog, executor.optimizer).build(plan)
        self.assertAlmostEqual(root.cost, executor.optimizer.costs.seq_cost(stats) + stats.rows * 0.025)

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
