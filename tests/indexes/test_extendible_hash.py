import random
import unittest

from engine.indexes import ExtendibleHash
from engine.storage.record import RID


class IdentityHash(ExtendibleHash):
    """Hash controlado para reproducir splits y colisiones en las pruebas."""

    @staticmethod
    def _hash_key(key):
        return key


class TestExtendibleHash(unittest.TestCase):
    def assert_invariants(self, index):
        self.assertEqual(len(index.directory), 1 << index.global_depth)
        count = 0
        for bucket in set(index.directory):
            self.assertLessEqual(bucket.local_depth, index.global_depth)
            aliases = [i for i, b in enumerate(index.directory) if b is bucket]
            self.assertEqual(len(aliases), 1 << (index.global_depth - bucket.local_depth))
            self.assertEqual(len({i & ((1 << bucket.local_depth) - 1) for i in aliases}), 1)
            page = bucket
            while page is not None:
                self.assertLessEqual(len(page.records), index.bucket_capacity)
                self.assertEqual(page.local_depth, bucket.local_depth)
                page = page.overflow
            for key, _ in bucket.entries():
                position = index._hash_key(key) & ((1 << index.global_depth) - 1)
                self.assertIs(index.directory[position], bucket)
                count += 1
        self.assertEqual(count, len(index))

    def test_search_duplicates_and_independent_results(self):
        index = ExtendibleHash(bucket_capacity=2)
        first, second = RID(0, 0), RID(0, 0, "aux")
        self.assertTrue(index.insert("café", first))
        self.assertTrue(index.insert("café", second))
        self.assertFalse(index.insert("café", first))
        result = index.search("café")
        self.assertCountEqual(result, [first, second])
        result.clear()
        self.assertEqual(len(index.search("café")), 2)
        self.assertEqual(index.search("missing"), [])
        self.assertEqual(len(index), 2)

    def test_split_with_and_without_directory_growth(self):
        index = IdentityHash(bucket_capacity=2)
        for key in [0, 2, 4]:
            index.insert(key, RID(0, key))
        self.assertEqual(index.global_depth, 2)
        self.assertIs(index.directory[1], index.directory[3])
        for key in [1, 3, 5]:
            index.insert(key, RID(0, key))
        self.assertEqual(index.global_depth, 2)
        self.assertIsNot(index.directory[1], index.directory[3])
        self.assert_invariants(index)

    def test_collision_overflow_can_later_split(self):
        index = IdentityHash(bucket_capacity=2, max_depth=3)
        for key in [0, 8, 16, 24, 32]:
            index.insert(key, RID(0, key))
        self.assertEqual(index.global_depth, 1)
        self.assertEqual(index.stats()["overflow_buckets"], 2)
        index.insert(4, RID(1, 0))
        self.assertEqual(index.global_depth, 3)
        for key in [0, 8, 16, 24, 32]:
            self.assertEqual(index.search(key), [RID(0, key)])
        self.assertEqual(index.search(4), [RID(1, 0)])
        self.assert_invariants(index)

    def test_repeated_key_over_capacity(self):
        index = ExtendibleHash(bucket_capacity=2)
        for slot in range(30):
            index.insert(7, RID(0, slot))
        self.assertEqual(index.global_depth, 1)
        self.assertEqual(len(index.search(7)), 30)
        self.assertEqual(index.delete(7, RID(0, 12)), 1)
        self.assertEqual(index.delete(7, RID(0, 12)), 0)
        self.assertEqual(index.delete(7), 29)
        self.assertEqual(index.stats()["overflow_buckets"], 0)
        self.assert_invariants(index)

    def test_numeric_equality_and_supported_keys(self):
        index = ExtendibleHash()
        for slot, key in enumerate([-12, 0.0, 1, 1.25, "1", ""]):
            index.insert(key, RID(0, slot))
        self.assertEqual(index.search(-0.0), [RID(0, 1)])
        self.assertFalse(index.insert(1.0, RID(0, 2)))
        self.assertEqual(index.search(1.0), [RID(0, 2)])
        self.assertEqual(index.search("1"), [RID(0, 4)])
        self.assert_invariants(index)

    def test_delete_merges_and_shrinks(self):
        index = IdentityHash(bucket_capacity=2)
        for key in range(32):
            index.insert(key, RID(key, 0))
        self.assertGreater(index.global_depth, 1)
        for key in range(32):
            self.assertEqual(index.delete(key), 1)
            self.assertEqual(index.search(key), [])
            self.assert_invariants(index)
        self.assertEqual(index.global_depth, 1)
        self.assertEqual(index.stats()["num_buckets"], 2)
        self.assertEqual(index.delete(99), 0)

    def test_mixed_operations_against_reference(self):
        rng = random.Random(42)
        index = ExtendibleHash(bucket_capacity=3, max_depth=6)
        expected = {}
        for _ in range(800):
            key, rid = rng.randrange(50), RID(rng.randrange(4), rng.randrange(8))
            if rng.random() < 0.65:
                entries = expected.setdefault(key, set())
                self.assertEqual(index.insert(key, rid), rid not in entries)
                entries.add(rid)
            elif rng.random() < 0.5:
                entries = expected.setdefault(key, set())
                self.assertEqual(index.delete(key, rid), int(rid in entries))
                entries.discard(rid)
            else:
                self.assertEqual(index.delete(key), len(expected.pop(key, set())))
            self.assertCountEqual(index.search(key), expected.get(key, set()))
            self.assert_invariants(index)
        for key, entries in expected.items():
            self.assertCountEqual(index.search(key), entries)

    def test_stats_count_shared_buckets_once(self):
        index = IdentityHash(bucket_capacity=2)
        for key in [0, 2, 4]:
            index.insert(key, RID(0, key))
        self.assertEqual(index.stats(), {
            "global_depth": 2, "directory_size": 4, "num_buckets": 3,
            "overflow_buckets": 0, "entries": 3, "load_factor": 0.5,
        })
        index.clear()
        self.assertEqual(len(index), 0)
        self.assertEqual(index.search(0), [])
        self.assertEqual(index.global_depth, 1)

    def test_invalid_parameters_keys_and_rids(self):
        for capacity in [0, -1, 1.5, True]:
            with self.assertRaises(ValueError):
                ExtendibleHash(bucket_capacity=capacity)
        for depth in [0, 21, 1.5, True]:
            with self.assertRaises(ValueError):
                ExtendibleHash(max_depth=depth)
        index = ExtendibleHash()
        for key in [None, [], {}, True, b"x"]:
            with self.assertRaises(TypeError):
                index.insert(key, RID(0, 0))
        for key in [float("nan"), float("inf"), -float("inf")]:
            with self.assertRaises(ValueError):
                index.search(key)
        for rid in [RID(-1, 0), RID(0, -1), RID(0, 0, "bad"), RID(True, 0)]:
            with self.assertRaises(ValueError):
                index.insert(1, rid)
        with self.assertRaises(TypeError):
            index.insert(1, (0, 0))
        self.assertEqual(len(index), 0)


if __name__ == "__main__":
    unittest.main()
