import math
import unittest

from engine.spatial.geometry import MBR, Point


class TestPoint(unittest.TestCase):
    def test_valid_points(self):
        self.assertEqual(Point(-12.0464, -77.0428), Point(-12.0464, -77.0428))
        for lat, lon in [(90, 180), (-90, -180), (0, 0)]:
            Point(lat, lon)

    def test_rejects_invalid_coordinates(self):
        for lat, lon in [(91, 0), (0, -181), (math.nan, 0), (0, math.inf), (True, 0), ("1", 0), (None, 0)]:
            with self.subTest(lat=lat, lon=lon), self.assertRaises(ValueError):
                Point(lat, lon)


class TestMBR(unittest.TestCase):
    def setUp(self):
        self.a = MBR(0, 0, 2, 4)      # alto 2, ancho 4
        self.b = MBR(1, 3, 5, 6)      # se solapa con a en [1,2] x [3,4]
        self.c = MBR(10, 10, 11, 11)  # lejos de ambos

    def test_rejects_inverted_bounds(self):
        with self.assertRaises(ValueError):
            MBR(2, 0, 1, 1)
        with self.assertRaises(ValueError):
            MBR(0, 5, 1, 4)

    def test_from_points(self):
        p = Point(-12, -77)
        self.assertEqual(MBR.from_point(p), MBR(-12, -77, -12, -77))
        self.assertEqual(MBR.of_points([Point(1, 5), Point(-2, 3), Point(0, 9)]), MBR(-2, 3, 1, 9))
        with self.assertRaises(ValueError):
            MBR.of_points([])

    def test_area_margin_and_union(self):
        self.assertEqual(self.a.area(), 8)
        self.assertEqual(self.a.margin(), 6)
        self.assertEqual(MBR.from_point(Point(1, 1)).area(), 0)
        self.assertEqual(self.a.union(self.b), MBR(0, 0, 5, 6))
        self.assertEqual(self.a.union(self.b), self.b.union(self.a))

    def test_enlargement(self):
        self.assertEqual(self.a.enlargement(self.b), 30 - 8)
        self.assertEqual(self.a.enlargement(MBR(1, 1, 2, 2)), 0)  # ya contenido

    def test_intersects_and_overlap(self):
        self.assertTrue(self.a.intersects(self.b))
        self.assertEqual(self.a.overlap(self.b), 1)
        self.assertFalse(self.a.intersects(self.c))
        self.assertEqual(self.a.overlap(self.c), 0)
        touching = MBR(2, 4, 3, 5)  # comparte solo la esquina (2, 4)
        self.assertTrue(self.a.intersects(touching))
        self.assertEqual(self.a.overlap(touching), 0)

    def test_contains_point_includes_border(self):
        self.assertTrue(self.a.contains_point(Point(1, 1)))
        self.assertTrue(self.a.contains_point(Point(2, 4)))
        self.assertFalse(self.a.contains_point(Point(2.0001, 1)))


if __name__ == "__main__":
    unittest.main()
