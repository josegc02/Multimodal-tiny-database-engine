import os
import random
import tempfile
import unittest

from engine.indexes.rtree import RTree
from engine.spatial.distance import Metric, distance
from engine.spatial.geometry import Point
from engine.storage.record import RID


class TestKNN(unittest.TestCase):
    def test_matches_brute_force_with_ties_deletes_and_reopen(self):
        rng = random.Random(21)
        entries = [(Point(rng.uniform(-90, 90), rng.uniform(-180, 180)), RID(i, 0)) for i in range(180)]
        entries += [(Point(0, 0), RID(200 - i, 0)) for i in range(20)]
        entries += [(Point(0, x), RID(300 + i, 0)) for i, x in enumerate([-1, 1, -179.99, 179.99])]
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "points")
            with RTree(path, 4) as tree:
                tree.bulk_load(entries)
                tree.delete(*entries[0])
                entries.pop(0)
            with RTree(path) as tree:
                for metric in Metric:
                    for center in [Point(0, 0), Point(89.99, 170), Point(-89.99, -170), Point(0, 180), Point(-12, -77)]:
                        expected = sorted([(p, rid, distance(center, p, metric)) for p, rid in entries],
                                          key=lambda row: (row[2], row[1].page_id))
                        for k in [0, 1, 10, 50, 100, 500]:
                            with self.subTest(metric=metric, center=center, k=k):
                                self.assertEqual(tree.knn(center, k, metric), expected[:k])
                                self.assertEqual(tree.last_stats.results, min(k, len(entries)))
                                self.assertLessEqual(tree.last_stats.nodes_visited, tree.stats()["nodes"])

    def test_empty_validation_and_pruning(self):
        with tempfile.TemporaryDirectory() as directory, RTree(os.path.join(directory, "p"), 4) as tree:
            self.assertEqual(tree.knn(Point(0, 0), 10), [])
            for k in [-1, 1.5, True, "2"]:
                with self.assertRaises(ValueError):
                    tree.knn(Point(0, 0), k)
            with self.assertRaises(ValueError):
                tree.knn(Point(0, 0), 0, "invalid")
            with self.assertRaises(TypeError):
                tree.knn((0, 0), 10)
            tree.insert(Point(0, 0), RID(999, 0))
            for i in range(150):
                tree.insert(Point(50 + i / 1000, 50), RID(i, 0))
            self.assertEqual(tree.knn(Point(0, 0), 1)[0][1], RID(999, 0))
            self.assertLess(tree.last_stats.nodes_visited, tree.stats()["nodes"])
