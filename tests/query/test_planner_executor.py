from collections import Counter
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from engine.indexes import ExtendibleHash
from engine.query import (
    Aggregate, BufferConfig, ExecutionStats, IndexInfo, OrderKey,
    QueryExecutor, QueryPlanner, TableStats,
)
from engine.storage.heap_file import HeapFile
from engine.storage.sequential_file import SequentialFile


class OrderedIndexDouble:
    """Contrato del futuro B+: recorrido completo con duplicados y NULLs al final."""

    def __init__(self, entries=()):
        self.entries = sorted(entries, key=lambda pair: (pair[0] is None, pair[0]))

    def iter_ordered(self, reverse=False):
        for _, rid in reversed(self.entries) if reverse else self.entries:
            yield rid


class TestQueryPlanner(unittest.TestCase):
    def setUp(self):
        self.planner = QueryPlanner(BufferConfig(3, 2))
        self.hash = IndexInfo("hash_id", "id", ExtendibleHash())
        self.ordered = IndexInfo("btree_id", "id", OrderedIndexDouble(), ordered=True, clustered=True)

    def test_equality_uses_index_only_when_selective(self):
        selective = TableStats(10000, 1000, {"id": 10000})
        nonselective = TableStats(10000, 1000, {"id": 2})
        self.assertEqual(self.planner.plan_equality(selective, "id", 42, [self.hash]).algorithm, "index_scan")
        self.assertEqual(self.planner.plan_equality(nonselective, "id", 42, [self.hash]).algorithm, "sequential_scan")
        self.assertEqual(self.planner.plan_equality(TableStats(10000, 1000), "id", 42, [self.hash]).algorithm,
                         "sequential_scan")

    def test_hash_cannot_satisfy_order_or_ordered_grouping(self):
        stats = TableStats(100, 10, {"id": 100})
        self.assertEqual(self.planner.plan_order_by(stats, "id", [self.hash]).algorithm, "external_sort")
        self.assertEqual(self.planner.plan_group_by(stats, "id", indexes=[self.hash]).algorithm,
                         "external_hash_group_by")

    def test_ordered_index_requires_real_capability_and_matching_field(self):
        stats = TableStats(100, 10)
        placeholder = IndexInfo("unfinished", "id", SimpleNamespace(insert=lambda key: None), ordered=True)
        invalid = IndexInfo("stale", "id", OrderedIndexDouble(), ordered=True, valid=False)
        for indexes in [[placeholder], [invalid], [self.ordered]]:
            self.assertEqual(self.planner.plan_order_by(stats, "other", indexes).algorithm, "external_sort")
        self.assertEqual(self.planner.plan_order_by(stats, "id", [placeholder, invalid]).algorithm, "external_sort")
        self.assertEqual(self.planner.plan_order_by(stats, "id", [self.ordered]).algorithm, "index_order_scan")
        self.assertEqual(self.planner.plan_order_by(stats, ("id", "other"), [self.ordered]).algorithm, "external_sort")

    def test_ordered_index_respects_direction_and_null_placement(self):
        stats = TableStats(100, 10)
        compatible = self.planner.plan_order_by(stats, [OrderKey("id", descending=True, nulls_first=True)], [self.ordered])
        incompatible = self.planner.plan_order_by(stats, [OrderKey("id", descending=True)], [self.ordered])
        self.assertEqual(compatible.algorithm, "index_order_scan")
        self.assertTrue(compatible.reverse)
        self.assertEqual(incompatible.algorithm, "external_sort")

    def test_ordered_grouping_and_expensive_unclustered_index(self):
        stats = TableStats(100, 10, {"id": 2})
        self.assertEqual(self.planner.plan_group_by(stats, "id", indexes=[self.ordered]).algorithm, "index_group_by")
        expensive = IndexInfo("unclustered", "id", OrderedIndexDouble(), ordered=True, lookup_pages=10000)
        self.assertEqual(self.planner.plan_group_by(stats, "id", indexes=[expensive]).algorithm, "external_hash_group_by")

    def test_small_join_uses_index_large_join_uses_partitioning(self):
        right = TableStats(10000, 1000, {"id": 10000})
        small = self.planner.plan_join(TableStats(2, 1), right, "foreign_id", "id", [self.hash])
        large = self.planner.plan_join(TableStats(10000, 1000), right, "foreign_id", "id", [self.hash])
        self.assertEqual(small.algorithm, "index_nested_loop_join")
        self.assertEqual(large.algorithm, "external_hash_join")
        self.assertEqual(self.planner.plan_join(TableStats(2, 1), right, ("a", "b"), ("id", "x"), [self.hash]).algorithm,
                         "external_hash_join")

    def test_invalid_index_is_not_used(self):
        invalid = IndexInfo("stale", "id", ExtendibleHash(), valid=False)
        stats = TableStats(100, 20, {"id": 100})
        self.assertEqual(self.planner.plan_equality(stats, "id", 1, [invalid]).algorithm, "sequential_scan")
        self.assertEqual(self.planner.plan_join(TableStats(1, 1), stats, "id", "id", [invalid]).algorithm,
                         "external_hash_join")

    def test_explain_cost_changes_with_buffer(self):
        stats = TableStats(5000, 500)
        tiny = self.planner.plan_order_by(stats, "id")
        large = QueryPlanner(BufferConfig(32, 128)).plan_order_by(stats, "id")
        self.assertGreater(tiny.estimated_io, large.estimated_io)
        self.assertEqual(tiny.explain()["buffer_pages"], 3)
        self.assertEqual(tiny.explain()["algorithm"], "external_sort")
        self.assertTrue(tiny.explain()["reason"])

    def test_empty_stats_and_validation(self):
        self.assertEqual(self.planner.plan_order_by(TableStats(0, 0), "id").estimated_io, 0)
        for args in [(-1, 0), (1, 0), (1.5, 1)]:
            with self.assertRaises(ValueError):
                TableStats(*args)
        with self.assertRaises(ValueError):
            TableStats(10, 1, {"id": 20})
        with self.assertRaises(ValueError):
            QueryPlanner(random_page_cost=0)


SCHEMA = [("id", "int"), ("k", "int"), ("value", "float")]


class TestQueryExecutor(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.temp_path = Path(self.tmp.name) / "spill"
        self.temp_path.mkdir()
        self.config = BufferConfig(3, 2, temp_dir=str(self.temp_path))
        self.planner = QueryPlanner(self.config)
        self.executor = QueryExecutor()
        self.serial = 0

    def storage(self, kind, rows):
        self.serial += 1
        path = Path(self.tmp.name) / str(self.serial)
        if kind == "heap":
            storage = HeapFile(str(path) + ".heap", SCHEMA, page_size=64)
        else:
            storage = SequentialFile(str(path) + ".main", str(path) + ".aux", SCHEMA, "id", page_size=64)
        self.addCleanup(storage.close)
        for row in rows:
            storage.insert(row)
        return storage

    def table_stats(self, storage):
        rows = [record for _, record in storage.scan()]
        pages = storage.num_pages if isinstance(storage, HeapFile) else storage.num_pages_main + storage.num_pages_aux
        return TableStats(len(rows), pages, {field: len({row[field] for row in rows}) for field in ["id", "k"]})

    def assert_no_temporaries(self):
        self.assertEqual(list(self.temp_path.iterdir()), [])

    def test_order_and_group_on_heap_and_sequential_active_records(self):
        rows = [{"id": i, "k": i % 5, "value": float(i)} for i in reversed(range(53))]
        for kind in ["heap", "seq"]:
            with self.subTest(kind=kind):
                storage = self.storage(kind, rows)
                deleted_rid = next(rid for rid, row in storage.scan() if row["id"] == 7)
                storage.delete(deleted_rid)
                active = [row for _, row in storage.scan()]
                stats = self.table_stats(storage)
                plan = self.planner.plan_order_by(stats, [OrderKey("k"), OrderKey("id", descending=True)])
                actual = list(self.executor.execute(plan, storage))
                self.assertEqual(actual, sorted(active, key=lambda r: (r["k"], -r["id"])))
                plan = self.planner.plan_group_by(stats, "k", {"total": Aggregate("sum", "value")})
                actual = {r["k"]: r["total"] for r in self.executor.execute(plan, storage)}
                self.assertEqual(actual, {k: sum(r["value"] for r in active if r["k"] == k) for k in range(5)})
                self.assert_no_temporaries()

    def test_real_hash_index_equality_and_index_join(self):
        right = self.storage("heap", [{"id": i, "k": i % 5, "value": float(i)} for i in range(40)])
        left = self.storage("seq", [{"id": 1, "k": 3, "value": 1.0}, {"id": 2, "k": 9, "value": 2.0}])
        index = ExtendibleHash()
        index.bulk_load_from_storage(right, "id")
        info = IndexInfo("hash_right_id", "id", index)
        stats = ExecutionStats()
        plan = self.planner.plan_equality(self.table_stats(right), "id", 12, [info])
        self.assertEqual(plan.algorithm, "index_scan")
        self.assertEqual(list(self.executor.execute(plan, right, stats=stats)), [{"id": 12, "k": 2, "value": 12.0}])
        self.assertEqual(stats.index_probes, 1)
        plan = self.planner.plan_join(self.table_stats(left), self.table_stats(right), "k", "id", [info])
        self.assertEqual(plan.algorithm, "index_nested_loop_join")
        self.assertEqual([(l["id"], r["id"]) for l, r in self.executor.execute(plan, left, right)], [(1, 3), (2, 9)])
        self.assert_no_temporaries()

    def test_external_join_for_full_tables_and_partial_close(self):
        lrows = [{"id": i, "k": i % 5, "value": float(i)} for i in range(30)]
        rrows = [{"id": i, "k": i % 7, "value": float(i)} for i in range(40)]
        left, right = self.storage("heap", lrows), self.storage("seq", rrows)
        plan = self.planner.plan_join(self.table_stats(left), self.table_stats(right), "k", "k")
        self.assertEqual(plan.algorithm, "external_hash_join")
        result = Counter((l["id"], r["id"]) for l, r in self.executor.execute(plan, left, right))
        expected = Counter((l["id"], r["id"]) for l in lrows for r in rrows if l["k"] == r["k"])
        self.assertEqual(result, expected)
        stream = self.executor.execute(plan, left, right)
        next(stream)
        stream.close()
        self.assert_no_temporaries()

    def test_ordered_index_contract_for_order_and_group(self):
        rows = [{"id": i, "k": i % 4, "value": float(i)} for i in range(30)]
        storage = self.storage("heap", rows)
        index = OrderedIndexDouble((record["k"], rid) for rid, record in storage.scan())
        info = IndexInfo("ordered_k", "k", index, ordered=True, clustered=True)
        stats = self.table_stats(storage)
        plan = self.planner.plan_order_by(stats, "k", [info])
        self.assertEqual(plan.algorithm, "index_order_scan")
        self.assertEqual(list(self.executor.execute(plan, storage)), sorted(rows, key=lambda r: r["k"]))
        plan = self.planner.plan_group_by(stats, "k", indexes=[info])
        self.assertEqual(plan.algorithm, "index_group_by")
        self.assertEqual({r["k"]: r["count"] for r in self.executor.execute(plan, storage)}, Counter(r["k"] for r in rows))
        self.assert_no_temporaries()

    def test_equality_scan_null_and_missing_join_source(self):
        rows = [{"id": i, "k": i % 2, "value": float(i)} for i in range(10)]
        storage = self.storage("heap", rows)
        stats = self.table_stats(storage)
        plan = self.planner.plan_equality(stats, "k", 1)
        self.assertEqual(list(self.executor.execute(plan, storage)), [r for r in rows if r["k"] == 1])
        plan = self.planner.plan_equality(stats, "k", None)
        self.assertEqual(list(self.executor.execute(plan, storage)), [])
        plan = self.planner.plan_join(stats, stats, "id", "id")
        with self.assertRaises(ValueError):
            list(self.executor.execute(plan, storage))
        self.assert_no_temporaries()


if __name__ == "__main__":
    unittest.main()
