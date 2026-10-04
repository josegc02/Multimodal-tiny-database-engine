import os
import random
import tempfile
import unittest
from unittest.mock import patch

from engine.concurrency.lock_manager import LockManager
from engine.concurrency.transaction_manager import TransactionManager
from engine.indexes import ExtendibleHash
from engine.indexes.bplus_tree_unclustered import BPlusTreeUnclustered
from engine.query.catalog import Catalog
from engine.query.parser import parse_script
from engine.query.planner import IndexInfo
from engine.query.statement_executor import StatementExecutor
from engine.storage.heap_file import HeapFile
from engine.storage.sequential_file import SequentialFile

SCHEMA = [("id", "int"), ("grupo", "int"), ("nombre", "str", 8)]


def index_entries(index):
    """Multiconjunto ordenado de pares (clave, RID) de un índice."""
    if isinstance(index, ExtendibleHash):
        pairs = [pair for bucket in dict.fromkeys(index.directory) for pair in bucket.entries()]
    else:
        pairs = list(index.iter_range())
    return sorted(pairs, key=repr)


def storage_entries(storage, column):
    return sorted(((record[column], rid) for rid, record in storage.scan()), key=repr)


class Database:
    def __init__(self, kind):
        self.dir = tempfile.mkdtemp()
        path = os.path.join(self.dir, "t")
        self.storage = (HeapFile(path + ".heap", SCHEMA, page_size=256) if kind == "heap" else
                        SequentialFile(path + ".main", path + ".aux", SCHEMA, "id", page_size=256))
        self.catalog = Catalog()
        self.catalog.register_table("t", self.storage)
        self.hash = ExtendibleHash(bucket_capacity=4)
        self.bplus = BPlusTreeUnclustered(os.path.join(self.dir, "grupo.bpt"), "int", order=8)
        self.catalog.register_index("t", "id", self.hash, IndexInfo("t_id", "id", self.hash))
        self.catalog.register_index("t", "grupo", self.bplus, IndexInfo("t_grupo", "grupo", self.bplus, ordered=True))
        self.binding = self.catalog.table("t")
        lm = LockManager()
        self.session = StatementExecutor(TransactionManager(lm, storage=self.catalog), lm, self.catalog)

    def run(self, sql):
        result = None
        for statement in parse_script(sql):
            result = self.session.execute(statement)
        return result

    def close(self):
        self.bplus.close()
        self.storage.close()


class TestIncrementalIndexMaintenance(unittest.TestCase):
    def assert_indexes_match_storage(self, db):
        self.assertEqual(index_entries(db.hash), storage_entries(db.storage, "id"))
        self.assertEqual(index_entries(db.bplus), storage_entries(db.storage, "grupo"))
        self.assertTrue(all(registered.valid for registered in db.binding.indexes.values()))
        self.assertEqual(db.binding.statistics.rows, sum(1 for _ in db.storage.scan()))

    def random_workload(self, db, steps=120, seed=3):
        rng = random.Random(seed)
        next_id = 0
        for step in range(steps):
            action = rng.random()
            if action < 0.5:
                rows = ", ".join(f"({next_id + i}, {rng.randrange(10)}, 'n{next_id + i}')" for i in range(3))
                next_id += 3
                db.run(f"INSERT INTO t VALUES {rows};")
            elif action < 0.75:
                db.run(f"DELETE FROM t WHERE grupo = {rng.randrange(10)} AND id > {rng.randrange(next_id + 1)};")
            else:
                db.run(f"BEGIN; INSERT INTO t VALUES ({next_id}, 99, 'tmp'); "
                       f"DELETE FROM t WHERE grupo = {rng.randrange(10)}; ROLLBACK;")
                next_id += 1
            if step % 10 == 0:
                self.assert_indexes_match_storage(db)
        self.assert_indexes_match_storage(db)

    def test_heap_indexes_are_updated_without_rebuilding(self):
        db = Database("heap")
        try:
            with patch.object(db.binding, "refresh_indexes", side_effect=AssertionError("reconstrucción")), \
                    patch.object(db.binding, "analyze", wraps=db.binding.analyze) as analyze:
                self.random_workload(db)
            # Auto-analyze ocasional, no un scan completo por sentencia.
            self.assertLess(analyze.call_count, 15)
            self.assertEqual(db.run("SELECT COUNT(*) AS n FROM t WHERE grupo = 99;"), [{"n": 0}])
        finally:
            db.close()

    def test_sequential_indexes_are_rebuilt_once_per_statement(self):
        db = Database("sequential")
        try:
            self.random_workload(db, steps=60)
            with patch.object(db.binding, "refresh_indexes", wraps=db.binding.refresh_indexes) as refresh:
                db.run("INSERT INTO t VALUES (1000, 1, 'a'), (1001, 2, 'b'), (1002, 3, 'c');")
            self.assertEqual(refresh.call_count, 1)
            self.assert_indexes_match_storage(db)
        finally:
            db.close()

    def test_equality_on_indexed_column_uses_index_after_bulk_growth(self):
        db = Database("heap")
        try:
            for i in range(0, 600, 3):
                db.run(f"INSERT INTO t VALUES ({i}, {i % 7}, 'x'), ({i + 1}, 1, 'y'), ({i + 2}, 2, 'z');")
            executor = db.session.query_executor
            node = executor.explain("SELECT * FROM t WHERE id = 42")
            while node["operation"] != "Scan":
                node = node["children"][0]
            self.assertEqual(node["physical"]["algorithm"], "index_scan")
        finally:
            db.close()

    def test_statistics_follow_writes_without_scanning(self):
        db = Database("heap")
        try:
            db.run("INSERT INTO t VALUES (5, 1, 'a'), (50, 2, 'b');")
            stats = db.binding.statistics
            self.assertEqual((stats.rows, stats.value_bounds["id"]), (2, (5, 50)))
            db.run("INSERT INTO t VALUES (-3, 1, 'c');")
            self.assertEqual(db.binding.statistics.value_bounds["id"], (-3, 50))
            db.run("DELETE FROM t WHERE id = 50;")
            self.assertEqual(db.binding.statistics.rows, 2)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
