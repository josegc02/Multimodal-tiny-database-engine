import os
import random
import tempfile
import unittest

from engine.concurrency.lock_manager import LockManager
from engine.concurrency.transaction_manager import TransactionManager
from engine.indexes import ExtendibleHash
from engine.indexes.bplus_tree_unclustered import BPlusTreeUnclustered
from engine.query.catalog import Catalog
from engine.query.parser import parse, parse_script
from engine.query.planner import IndexInfo, QueryPlanner, TableStats
from engine.query.sql_executor import SQLExecutor
from engine.query.statement_executor import StatementExecutor
from engine.storage.clustered_file import ClusteredBPlusFile, DuplicateKeyError
from engine.storage.heap_file import HeapFile

SCHEMA = [("id", "int"), ("nombre", "str", 12), ("precio", "float")]
N = 2000


def records(n=N, seed=5):
    keys = list(range(n))
    random.Random(seed).shuffle(keys)
    return [{"id": k, "nombre": f"p{k}", "precio": k / 4} for k in keys]


def scan_algorithm(executor, sql):
    """Algoritmo físico elegido para el Scan de la consulta."""
    node = executor.explain(sql)
    while node["operation"] != "Scan":
        node = node["children"][0]
    return node["physical"]["algorithm"]


class TestRangePlanning(unittest.TestCase):
    def setUp(self):
        self.stats = TableStats(10_000, 400, {"id": 10_000}, {"id": (0, 9_999)})
        self.index = IndexInfo("t_id", "id", BPlusTreeUnclustered.__new__(BPlusTreeUnclustered), ordered=True)

    def test_selective_range_uses_index(self):
        plan = QueryPlanner().plan_range(self.stats, "id", 100, 120, indexes=[self.index])
        self.assertEqual(plan.algorithm, "index_range_scan")
        self.assertEqual(plan.explain()["range"], "100 <= id <= 120")

    def test_wide_range_prefers_sequential_scan(self):
        plan = QueryPlanner().plan_range(self.stats, "id", 100, None, indexes=[self.index])
        self.assertEqual(plan.algorithm, "sequential_scan")

    def test_hash_index_cannot_serve_ranges(self):
        hashed = IndexInfo("t_id_hash", "id", ExtendibleHash())
        self.assertFalse(hashed.supports_range)
        plan = QueryPlanner().plan_range(self.stats, "id", 1, 2, indexes=[hashed])
        self.assertEqual(plan.algorithm, "sequential_scan")


class TestRangeQueriesWithUnclusteredIndex(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        # Páginas pequeñas: la tabla ocupa muchas páginas y el índice resulta rentable.
        cls.heap = HeapFile(os.path.join(cls.dir, "t.heap"), SCHEMA, page_size=256)
        for record in records():
            cls.heap.insert(record)
        cls.catalog = Catalog()
        cls.catalog.register_table("t", cls.heap)
        index = BPlusTreeUnclustered(os.path.join(cls.dir, "t_id.bpt"), "int", order=64)
        cls.catalog.register_index("t", "id", index, IndexInfo("t_id", "id", index, ordered=True))
        cls.executor = SQLExecutor(cls.catalog)

    @classmethod
    def tearDownClass(cls):
        cls.heap.close()

    def ids(self, sql):
        return sorted(row["id"] for row in self.executor.execute(sql))

    def test_operators_use_index_and_return_exact_rows(self):
        cases = {
            "SELECT id FROM t WHERE id BETWEEN 100 AND 110": range(100, 111),
            "SELECT id FROM t WHERE id >= 1995": range(1995, 2000),
            "SELECT id FROM t WHERE id > 1995": range(1996, 2000),
            "SELECT id FROM t WHERE id < 4": range(0, 4),
            "SELECT id FROM t WHERE 4 >= id": range(0, 5),
            "SELECT id FROM t WHERE id > 5 AND id > 8 AND id < 12": range(9, 12),
            "SELECT id FROM t WHERE id >= -3 AND id <= 2": range(0, 3),
            "SELECT id FROM t WHERE t.id BETWEEN 7 AND 9 AND precio > 1.9": range(8, 10),
        }
        for sql, expected in cases.items():
            with self.subTest(sql=sql):
                self.assertEqual(scan_algorithm(self.executor, sql), "index_range_scan")
                self.assertEqual(self.ids(sql), list(expected))

    def test_unselective_or_incompatible_ranges_fall_back_to_scan(self):
        for sql, expected in {
            "SELECT id FROM t WHERE id > 10": range(11, N),
            "SELECT id FROM t WHERE id BETWEEN 2.5 AND 5": range(3, 6),  # int vs float
            "SELECT id FROM t WHERE NOT id BETWEEN 3 AND 1990": list(range(0, 3)) + list(range(1991, N)),
        }.items():
            with self.subTest(sql=sql):
                self.assertEqual(scan_algorithm(self.executor, sql), "sequential_scan")
                self.assertEqual(self.ids(sql), list(expected))

    def test_empty_range(self):
        self.assertEqual(self.ids("SELECT id FROM t WHERE id > 10 AND id < 5"), [])


class TestClusteredTable(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.table = ClusteredBPlusFile(os.path.join(self.dir, "t.bpt"), SCHEMA, "id", page_size=512)

    def tearDown(self):
        self.table.close()

    def test_storage_interface_keeps_records_ordered_by_key(self):
        for record in records(300):
            rid = self.table.insert(record)
            self.assertEqual(self.table.get(rid), record)
        self.assertEqual([r["id"] for _, r in self.table.scan()], list(range(300)))
        rid, record = self.table.search_by_key(150)[0]
        self.assertTrue(self.table.delete(rid))
        self.assertEqual(self.table.search_by_key(150), [])
        self.assertEqual([r["id"] for _, r in self.table.range_search(148, 152)], [148, 149, 151, 152])
        with self.assertRaises(DuplicateKeyError):
            self.table.insert({"id": 7, "nombre": "dup", "precio": 0.0})

    def test_reopen_preserves_records(self):
        for record in records(100):
            self.table.insert(record)
        self.table.close()
        self.table = ClusteredBPlusFile(os.path.join(self.dir, "t.bpt"), SCHEMA, "id", page_size=512)
        self.assertEqual(len(list(self.table.scan())), 100)

    def test_sql_uses_primary_clustered_index_and_supports_rollback(self):
        catalog = Catalog()
        catalog.register_table("t", self.table, {"id": self.table.primary_index_info("t_pk")})
        lm = LockManager()
        session = StatementExecutor(TransactionManager(lm, storage=catalog), lm, catalog)
        executor = session.query_executor

        def run(sql):
            result = None
            for statement in parse_script(sql):
                result = session.execute(statement)
            return result

        run("INSERT INTO t VALUES " + ", ".join(
            f"({r['id']}, '{r['nombre']}', {r['precio']})" for r in records(500)) + ";")
        self.assertEqual(scan_algorithm(executor, "SELECT * FROM t WHERE id = 42"), "index_scan")
        self.assertEqual(scan_algorithm(executor, "SELECT * FROM t WHERE id BETWEEN 10 AND 20"),
                         "index_range_scan")
        self.assertEqual(scan_algorithm(executor, "SELECT * FROM t WHERE precio > 1"), "sequential_scan")
        self.assertEqual([r["id"] for r in run("SELECT id FROM t WHERE id BETWEEN 10 AND 12;")], [10, 11, 12])
        self.assertEqual([r["id"] for r in run("SELECT id FROM t ORDER BY id DESC LIMIT 2;")], [499, 498])

        run("BEGIN; DELETE FROM t WHERE id BETWEEN 100 AND 199; INSERT INTO t VALUES (900, 'x', 1.0); ROLLBACK;")
        self.assertEqual(run("SELECT COUNT(*) AS n FROM t;"), [{"n": 500}])
        self.assertEqual(run("SELECT nombre FROM t WHERE id = 150;"), [{"nombre": "p150"}])
        self.assertEqual(run("SELECT * FROM t WHERE id = 900;"), [])
        self.assertEqual(lm.lock_table, {})


class TestCreateTableUsingBtree(unittest.TestCase):
    def test_parser_accepts_btree_storage(self):
        statement = parse("CREATE TABLE t (id INT, nombre VARCHAR(10)) USING BTREE")
        self.assertEqual(statement.storage_method, "btree")


if __name__ == "__main__":
    unittest.main()
