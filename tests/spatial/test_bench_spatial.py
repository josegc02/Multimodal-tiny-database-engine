import csv
import os
import shutil
import tempfile
import unittest

from benchmarks import bench_spatial
from benchmarks.generate_spatial_datasets import generate_points, generate_queries
from engine.spatial.distance import haversine
from engine.spatial.geometry import Point


class TestSpatialBenchmark(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)

    def test_sequential_scan_matches_brute_force(self):
        points = generate_points(300)
        centers = [Point(q["lat"], q["lon"]) for q in generate_queries(5)]
        heap, _ = bench_spatial.build_heap(points, self.dir)
        self.addCleanup(heap.close)
        for c in centers:
            expected = {p["id"] for p in points if haversine(c, p["ubicacion"]) <= 5000}
            self.assertEqual(set(bench_spatial.sequential_range(heap, c, 5000)), expected)
            nearest = sorted((haversine(c, p["ubicacion"]), p["id"]) for p in points)[:10]
            self.assertEqual([(i, d) for i, d in bench_spatial.sequential_knn(heap, c, 10)],
                             [(i, d) for d, i in nearest])

    def test_full_run_writes_results_and_plots(self):
        bench_spatial.main(["--sizes", "200", "400", "--queries", "3", "--repetitions", "2",
                            "--sin-postgis", "--output-dir", self.dir])
        with open(os.path.join(self.dir, "spatial_comparison.csv"), encoding="utf-8") as stream:
            rows = {(r["tecnica"], r["n_registros"]): r for r in csv.DictReader(stream)}
        rtree = rows[("R-Tree", "400")]
        self.assertGreater(float(rtree["espacio_indice_bytes"]), 0)
        self.assertGreater(float(rtree["nodos_visitados_knn"]), 0)
        self.assertEqual(rows[("Secuencial", "400")]["tiempo_construccion_seg"], "NA")
        self.assertEqual(rows[("GiST (PostGIS)", "400")]["tiempo_rango_5km_seg"], "NA")
        for name in ["construccion", "rango_1km", "rango_5km", "rango_10km", "knn_10", "knn_50", "knn_100"]:
            self.assertTrue(os.path.exists(os.path.join(self.dir, f"spatial_tiempo_{name}.png")), name)
        self.assertTrue(os.path.exists(os.path.join(self.dir, "spatial_espacio_indice.png")))


@unittest.skipUnless(os.environ.get("BD2_POSTGIS_DSN"), "define BD2_POSTGIS_DSN para probar contra PostGIS")
class TestAgainstPostGIS(unittest.TestCase):
    def test_gist_matches_sequential(self):
        points = generate_points(2000)
        centers = [Point(q["lat"], q["lon"]) for q in generate_queries(10)]
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory, True)
        heap, _ = bench_spatial.build_heap(points, directory)
        self.addCleanup(heap.close)
        _, expected = bench_spatial.bench_sequential(heap, centers)
        row = bench_spatial.bench_gist(points, centers, expected, os.environ["BD2_POSTGIS_DSN"])
        self.assertGreater(row["espacio_indice_bytes"], 0)


if __name__ == "__main__":
    unittest.main()
