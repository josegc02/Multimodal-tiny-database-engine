import tempfile
import unittest

from benchmarks.bench_spatial import bench_rtree, bench_sequential
from benchmarks.generate_spatial_datasets import generate_points, generate_queries


class TestSpatialBenchmark(unittest.TestCase):
    def test_sequential_and_rtree_produce_measurements(self):
        points, queries = generate_points(30), generate_queries(3)
        sequential = bench_sequential(points, queries)
        with tempfile.TemporaryDirectory() as directory:
            rtree = bench_rtree(points, queries, directory)
        for result in (sequential, rtree):
            self.assertGreaterEqual(result["tiempo_rango_1km_seg"], 0)
            self.assertGreaterEqual(result["tiempo_knn_10_seg"], 0)
        self.assertGreater(rtree["espacio_disco_bytes"], 0)
