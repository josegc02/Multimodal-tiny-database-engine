from collections import Counter
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

from engine.query import (
    Aggregate, BufferConfig, ExecutionStats, OrderKey,
    external_hash_group_by, external_hash_join, external_sort,
)


class OnePass:
    """Fuente que detecta relecturas accidentales o materialización vía len()."""

    def __init__(self, rows):
        self.rows = rows
        self.used = False

    def __iter__(self):
        if self.used:
            raise AssertionError("La entrada solo puede recorrerse una vez")
        self.used = True
        yield from self.rows

    def __len__(self):
        raise AssertionError("No se debe materializar la entrada")


class ExternalTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = BufferConfig(3, 2, temp_dir=self.tmp.name)
        self.stats = ExecutionStats()

    def assert_limits_and_cleanup(self):
        self.assertLessEqual(self.stats.peak_buffered_records, self.config.capacity)
        self.assertLessEqual(self.stats.peak_open_files, self.config.buffer_pages)
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [])


class TestExternalSort(ExternalTestCase):
    def test_multiple_merge_passes_with_tiny_buffer(self):
        rows = [{"k": i % 37, "id": i} for i in range(501)]
        random.Random(42).shuffle(rows)
        actual = list(external_sort(OnePass(rows), "k", config=self.config, stats=self.stats))
        self.assertEqual(actual, sorted(rows, key=lambda row: row["k"]))
        self.assertEqual(self.stats.initial_runs, 84)
        self.assertGreaterEqual(self.stats.merge_passes, 6)
        self.assertGreater(self.stats.records_written, len(rows))
        self.assertEqual(self.stats.peak_buffered_records, 6)
        self.assert_limits_and_cleanup()

    def test_stability_and_mixed_directions_with_nulls(self):
        rows = [{"id": i, "a": i % 3, "b": None if i % 4 == 0 else i % 7} for i in range(80)]
        order = [OrderKey("a", descending=True), OrderKey("b", nulls_first=True)]
        expected = sorted(rows, key=lambda r: (-r["a"], r["b"] is not None, r["b"] or 0))
        self.assertEqual(list(external_sort(rows, order, config=self.config, stats=self.stats)), expected)
        self.assert_limits_and_cleanup()

    def test_empty_singleton_and_unicode_payload(self):
        for rows in [[], [{"k": 1}], [{"k": "ñ", "v": "café\x00😀"}, {"k": "a", "v": None}]]:
            with self.subTest(rows=rows):
                actual = list(external_sort(rows, "k", config=self.config, stats=self.stats))
                self.assertEqual(actual, sorted(rows, key=lambda r: r["k"]))
                self.assert_limits_and_cleanup()

    def test_reused_source_dictionary_is_snapshotted(self):
        def rows():
            row = {}
            for i in range(100, -1, -1):
                row["k"] = i
                yield row
        result = list(external_sort(rows(), "k", config=self.config, stats=self.stats))
        self.assertEqual([r["k"] for r in result], list(range(101)))
        self.assert_limits_and_cleanup()

    def test_runs_use_struct_format_and_cleanup_on_close(self):
        result = external_sort(({"k": i} for i in reversed(range(100))), "k",
                               config=self.config, stats=self.stats)
        self.assertEqual(next(result), {"k": 0})
        files = list(Path(self.tmp.name).rglob("*.bin"))
        self.assertTrue(files)
        for file in files:
            with file.open("rb") as fh:
                self.assertEqual(fh.read(4), b"EXT1")
        result.close()
        self.assert_limits_and_cleanup()

    def test_source_failure_cleans_already_spilled_runs(self):
        def broken():
            for i in range(30):
                yield {"k": i}
            raise OSError("fallo del storage")
        with self.assertRaises(OSError):
            list(external_sort(broken(), "k", config=self.config, stats=self.stats))
        self.assertGreater(self.stats.records_written, 0)
        self.assert_limits_and_cleanup()

    def test_invalid_keys_and_fields_cleanup(self):
        for row, error in [({"k": float("nan")}, ValueError), ({"k": []}, TypeError), ({"x": 1}, KeyError)]:
            with self.subTest(row=row), self.assertRaises(error):
                list(external_sort([row], "k", config=self.config))
            self.assert_limits_and_cleanup()
        with self.assertRaises(ValueError):
            list(external_sort([], [], config=self.config))


class TestExternalGroupBy(ExternalTestCase):
    def test_repartition_with_more_groups_than_buffer(self):
        rows = [{"k": i % 113, "v": i} for i in range(1100)]
        result = list(external_hash_group_by(OnePass(rows), "k", config=self.config, stats=self.stats))
        self.assertEqual({r["k"]: r["count"] for r in result}, Counter(r["k"] for r in rows))
        self.assertGreater(self.stats.repartitions, 0)
        self.assert_limits_and_cleanup()

    def test_forced_hash_collisions_use_external_sort_fallback(self):
        rows = [{"k": i % 97} for i in range(601)]
        with patch("engine.query.external_algorithms._partition_id", return_value=0):
            result = list(external_hash_group_by(OnePass(rows), "k", config=self.config, stats=self.stats))
        self.assertEqual({r["k"]: r["count"] for r in result}, Counter(r["k"] for r in rows))
        self.assertGreater(self.stats.skew_fallbacks, 0)
        self.assertGreater(self.stats.merge_passes, 0)
        self.assert_limits_and_cleanup()

    def test_hot_group_uses_one_aggregate_state(self):
        result = list(external_hash_group_by(({"k": "hot"} for _ in range(3000)), "k",
                                             config=self.config, stats=self.stats))
        self.assertEqual(result, [{"k": "hot", "count": 3000}])
        self.assertEqual(self.stats.repartitions, 0)
        self.assertLessEqual(self.stats.peak_buffered_records, 2)
        self.assert_limits_and_cleanup()

    def test_aggregates_composite_keys_numeric_equality_and_nulls(self):
        rows = [
            {"a": 1, "b": "x", "v": 3}, {"a": 1.0, "b": "x", "v": None},
            {"a": 1.0, "b": "x", "v": 7}, {"a": None, "b": "x", "v": None},
            {"a": 0.0, "b": "y", "v": -2}, {"a": -0.0, "b": "y", "v": 4},
        ]
        specs = {"n": Aggregate(), "non_null": Aggregate("count", "v"), "total": Aggregate("sum", "v"),
                 "mean": Aggregate("avg", "v"), "low": Aggregate("min", "v"), "high": Aggregate("max", "v")}
        result = {(r["a"], r["b"]): r for r in external_hash_group_by(rows, ("a", "b"), specs,
                                                                    config=self.config, stats=self.stats)}
        self.assertEqual(result[1, "x"], {"a": 1, "b": "x", "n": 3, "non_null": 2,
                                         "total": 10, "mean": 5, "low": 3, "high": 7})
        self.assertEqual(result[None, "x"]["n"], 1)
        self.assertEqual(result[None, "x"]["non_null"], 0)
        self.assertIsNone(result[None, "x"]["total"])
        self.assertEqual(result[0, "y"]["mean"], 1)
        self.assert_limits_and_cleanup()

    def test_empty_input_and_global_aggregate(self):
        self.assertEqual(list(external_hash_group_by([], "k", config=self.config)), [])
        specs = {"n": Aggregate(), "total": Aggregate("sum", "v"), "mean": Aggregate("avg", "v")}
        self.assertEqual(list(external_hash_group_by([], [], specs, config=self.config)),
                         [{"n": 0, "total": None, "mean": None}])
        self.assertEqual(list(external_hash_group_by([{"v": 1}, {"v": 3}], [], specs, config=self.config)),
                         [{"n": 2, "total": 4, "mean": 2}])
        self.assert_limits_and_cleanup()

    def test_depth_limit_and_partial_consumption(self):
        config = BufferConfig(3, 1, max_partition_depth=0, temp_dir=self.tmp.name)
        result = external_hash_group_by(({"k": i} for i in range(150)), "k", config=config, stats=self.stats)
        self.assertEqual(next(result)["count"], 1)
        result.close()
        self.assertGreater(self.stats.skew_fallbacks, 0)
        self.assert_limits_and_cleanup()

    def test_aggregate_failure_and_partition_write_failure_cleanup(self):
        with self.assertRaises(TypeError):
            list(external_hash_group_by([{"k": 1, "v": "bad"}], "k", {"total": Aggregate("sum", "v")},
                                       config=self.config))
        with patch("engine.query.external_algorithms.write_record", side_effect=OSError("disco lleno")):
            with self.assertRaises(OSError):
                list(external_hash_group_by([{"k": 1}], "k", config=self.config))
        self.assert_limits_and_cleanup()


class TestExternalJoin(ExternalTestCase):
    def assert_join(self, left, right, *, config=None):
        actual = Counter((l["id"], r["id"]) for l, r in external_hash_join(
            OnePass(left), OnePass(right), "k", "key", config=config or self.config, stats=self.stats))
        expected = Counter((l["id"], r["id"]) for l in left for r in right
                           if l["k"] is not None and r["key"] is not None and l["k"] == r["key"])
        self.assertEqual(actual, expected)
        self.assert_limits_and_cleanup()

    def test_repartition_and_duplicates_against_nested_loop(self):
        left = [{"id": i, "k": i % 29} for i in range(180)]
        right = [{"id": i, "key": i % 31} for i in range(113)]
        self.assert_join(left, right)
        self.assertGreater(self.stats.repartitions, 0)

    def test_hot_key_many_to_many_uses_bounded_fallback(self):
        left = [{"id": i, "k": 7} for i in range(41)]
        right = [{"id": i, "key": 7.0} for i in range(19)]
        self.assert_join(left, right)
        self.assertGreater(self.stats.skew_fallbacks, 0)
        self.assertLessEqual(self.stats.peak_buffered_records, self.config.hash_capacity + 1)

    def test_forced_collisions_preserve_key_equality(self):
        left = [{"id": i, "k": i % 13} for i in range(70)]
        right = [{"id": i, "key": i % 17} for i in range(40)]
        with patch("engine.query.external_algorithms._partition_id", return_value=0):
            self.assert_join(left, right)
        self.assertGreater(self.stats.skew_fallbacks, 0)

    def test_builds_smaller_side_and_preserves_orientation(self):
        left = [{"id": i, "k": i % 4} for i in range(50)]
        right = [{"id": 100, "key": 2}]
        self.assert_join(left, right)
        self.assertEqual(self.stats.repartitions, 0)
        self.assertLessEqual(self.stats.peak_buffered_records, 2)

    def test_empty_no_matches_and_nulls(self):
        for left, right in [([], []), ([{"id": 1, "k": 1}], []),
                            ([{"id": 1, "k": 1}], [{"id": 2, "key": 2}]),
                            ([{"id": 1, "k": None}], [{"id": 2, "key": None}])]:
            with self.subTest(left=left, right=right):
                self.assert_join(left, right)

    def test_composite_keys_and_full_row_payloads(self):
        left = [{"id": 1, "a": 1, "b": "ñ", "name": "left"}, {"id": 2, "a": 1, "b": None}]
        right = [{"id": 9, "x": 1.0, "y": "ñ", "name": "right"}, {"id": 10, "x": 1, "y": None}]
        self.assertEqual(list(external_hash_join(left, right, ("a", "b"), ("x", "y"),
                                                config=self.config, stats=self.stats)), [(left[0], right[0])])
        self.assert_limits_and_cleanup()

    def test_depth_limit_fallback_and_close(self):
        config = BufferConfig(3, 2, max_partition_depth=0, temp_dir=self.tmp.name)
        result = external_hash_join(({"k": 1, "id": i} for i in range(100)),
                                    ({"k": 1, "id": i} for i in range(100)), "k", "k",
                                    config=config, stats=self.stats)
        next(result)
        result.close()
        self.assertGreater(self.stats.skew_fallbacks, 0)
        self.assert_limits_and_cleanup()

    def test_second_input_failure_cleans_first_partitions(self):
        def broken():
            yield {"k": 1}
            raise OSError("entrada interrumpida")
        with self.assertRaises(OSError):
            list(external_hash_join([{"k": 1}], broken(), "k", "k", config=self.config, stats=self.stats))
        self.assert_limits_and_cleanup()


class TestBufferValidation(unittest.TestCase):
    def test_invalid_buffer_configurations(self):
        for kwargs in [{"buffer_pages": 2}, {"buffer_pages": True}, {"records_per_page": 0},
                       {"records_per_page": 2.5}, {"max_partition_depth": -1}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                BufferConfig(**kwargs)

    def test_invalid_aggregate_specifications(self):
        for args in [("median", "v"), ("sum", None)]:
            with self.assertRaises(ValueError):
                Aggregate(*args)
        with self.assertRaises(ValueError):
            list(external_hash_group_by([], "k", {"k": Aggregate()}))
        with self.assertRaises(ValueError):
            list(external_hash_join([], [], ("a", "b"), "a"))


if __name__ == "__main__":
    unittest.main()
