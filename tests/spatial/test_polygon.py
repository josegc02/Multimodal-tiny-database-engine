import os
import random
import tempfile
import unittest
from pathlib import Path

from engine.indexes.rtree import RTree
from engine.spatial.geometry import MBR, Point, Polygon, load_districts
from engine.storage.record import RID


class TestPolygon(unittest.TestCase):
    def test_concave_borders_and_orientation(self):
        vertices = [Point(y, x) for y, x in [(0, 0), (0, 4), (1, 4), (1, 1), (4, 1), (4, 0)]]
        for ring in [vertices, vertices[::-1], vertices + vertices[:1]]:
            p = Polygon(ring)
            self.assertEqual(p.mbr(), MBR(0, 0, 4, 4))
            for point in [Point(.5, 3), Point(3, .5), Point(1, 1), Point(4, 0), Point(0, 2)]:
                self.assertTrue(p.contains(point))
            for point in [Point(2, 2), Point(-.001, 0), Point(4, 4)]:
                self.assertFalse(p.contains(point))

    def test_geojson_holes_and_district_loader(self):
        geometry = {"type": "Polygon", "coordinates": [
            [[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]],
            [[1, 1], [2, 1], [2, 2], [1, 2], [1, 1]]]}
        polygon, = Polygon.from_geojson(geometry)
        self.assertTrue(polygon.contains(Point(.5, .5)))
        self.assertFalse(polygon.contains(Point(1.5, 1.5)))
        self.assertTrue(polygon.contains(Point(1, 1.5)))
        districts = load_districts(Path(__file__).parent / "fixtures" / "districts.geojson")
        parts = districts["Distrito de prueba"]
        self.assertEqual(len(parts), 2)
        self.assertTrue(parts[0].contains(Point(-12.05, -77.05)))
        self.assertTrue(parts[1].contains(Point(-12.05, -76.85)))

    def test_invalid_polygon_and_geojson(self):
        for vertices in [[], [Point(0, 0)] * 3, [Point(0, 0), Point(1, 1), Point(2, 2)]]:
            with self.assertRaises(ValueError):
                Polygon(vertices)
        for obj in [None, {"type": "Point"}, {"type": "Polygon", "coordinates": []},
                    {"type": "Polygon", "coordinates": [[[1], [2], [3]]]}]:
            with self.assertRaises(ValueError):
                Polygon.from_geojson(obj)

    def test_tree_matches_scan_and_exact_triangle_oracle(self):
        triangle = Polygon([Point(0, 0), Point(0, 2), Point(2, 0)])
        rng = random.Random(22)
        points = [Point(rng.uniform(-1, 3), rng.uniform(-1, 3)) for _ in range(300)]
        points += [Point(0, 0), Point(1, 1), Point(1, 0), Point(2, 2)]
        expected = [RID(i, 0) for i, p in enumerate(points) if p.lat >= 0 and p.lon >= 0 and p.lat + p.lon <= 2]
        with tempfile.TemporaryDirectory() as directory, RTree(os.path.join(directory, "p"), 4) as tree:
            self.assertEqual(tree.within_polygon(triangle), [])
            tree.bulk_load((point, RID(i, 0)) for i, point in enumerate(points))
            self.assertEqual([rid for p, rid in tree.within_polygon(triangle)], expected)
            self.assertEqual(tree.last_stats.results, len(expected))
            self.assertLess(tree.last_stats.refined, len(points))
            concave = Polygon([Point(0, 0), Point(0, 2), Point(1, 1), Point(2, 2), Point(2, 0)])
            self.assertEqual([rid for p, rid in tree.within_polygon(concave)],
                             [RID(i, 0) for i, p in enumerate(points) if concave.contains(p)])
