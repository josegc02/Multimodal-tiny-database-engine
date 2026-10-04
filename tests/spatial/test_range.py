import math
import os
import random
import tempfile
import unittest

from engine.indexes.rtree import RTree
from engine.spatial.distance import Metric, distance
from engine.spatial.geometry import Point
from engine.storage.record import RID


class TestRadiusQuery(unittest.TestCase):
    def test_matches_scan_both_metrics_and_reopen(self):
        rng = random.Random(20)
        points = [Point(rng.uniform(-90, 90), rng.uniform(-180, 180)) for _ in range(250)]
        points += [Point(-12, -77), Point(-12, -77), Point(0, 179.99), Point(0, -179.99),
                   Point(90, 0), Point(90, 120), Point(-89.99, 20)]
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "points.rtree")
            with RTree(path, max_entries=5) as tree:
                tree.bulk_load((point, RID(i, 0)) for i, point in enumerate(points))
            with RTree(path) as tree:
                for metric in Metric:
                    for center in [points[-1], points[-3], points[-4], Point(-12, -77), Point(0, 0)]:
                        for radius in [0, 1_000, 5_000, 10_000, 5_000_000, 50_000_000]:
                            with self.subTest(metric=metric, center=center, radius=radius):
                                expected = [(p, RID(i, 0), distance(center, p, metric))
                                            for i, p in enumerate(points) if distance(center, p, metric) <= radius]
                                expected.sort(key=lambda row: (row[2], row[1].page_id))
                                self.assertEqual(tree.range_query(center, radius, metric), expected)
                                stats = tree.last_stats
                                self.assertEqual(stats.results, len(expected))
                                self.assertLessEqual(stats.results, stats.refined)
                                self.assertLessEqual(stats.refined, stats.candidates)
                                self.assertLessEqual(stats.nodes_visited, tree.stats()["nodes"])

    def test_boundary_empty_validation_and_pruning(self):
        with tempfile.TemporaryDirectory() as directory, RTree(os.path.join(directory, "p"), 4) as tree:
            center, point = Point(0, 0), Point(0, 0.01)
            self.assertEqual(tree.range_query(center, 1), [])
            for i in range(100):
                tree.insert(Point(40 + i / 100, 40), RID(i, 0))
            tree.insert(point, RID(100, 0))
            for metric in Metric:
                radius = distance(center, point, metric)
                self.assertEqual(len(tree.range_query(center, radius, metric)), 1)
                self.assertEqual(tree.range_query(center, math.nextafter(radius, 0), metric), [])
                self.assertLess(tree.last_stats.nodes_visited, tree.stats()["nodes"])
            for radius in (-1, math.nan, math.inf, "5", True):
                with self.assertRaises(ValueError):
                    tree.range_query(center, radius)
            with self.assertRaises(ValueError):
                tree.range_query(center, 5, "invalid")
            with self.assertRaises(TypeError):
                tree.range_query((0, 0), 5)
