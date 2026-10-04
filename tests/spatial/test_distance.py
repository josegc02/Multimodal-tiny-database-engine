import math
import random
import unittest

from engine.spatial.distance import (EARTH_RADIUS_M, METERS_PER_DEGREE, Metric, distance, euclidean,
                                     haversine, mindist, radius_to_mbr)
from engine.spatial.geometry import MBR, Point

LIMA = Point(-12.0464, -77.0428)
CUSCO = Point(-13.5320, -71.9675)


def law_of_cosines(a, b):
    """Fórmula alternativa del gran círculo, para comparar con Haversine."""
    phi1, phi2 = math.radians(a.lat), math.radians(b.lat)
    cos_angle = (math.sin(phi1) * math.sin(phi2)
                 + math.cos(phi1) * math.cos(phi2) * math.cos(math.radians(b.lon - a.lon)))
    return EARTH_RADIUS_M * math.acos(max(-1.0, min(1.0, cos_angle)))


def destination(origin, bearing_deg, distance_m):
    """Punto a `distance_m` metros de `origin` en el rumbo dado (sobre la esfera)."""
    phi1, lambda1 = math.radians(origin.lat), math.radians(origin.lon)
    theta, delta = math.radians(bearing_deg), distance_m / EARTH_RADIUS_M
    phi2 = math.asin(math.sin(phi1) * math.cos(delta) + math.cos(phi1) * math.sin(delta) * math.cos(theta))
    lambda2 = lambda1 + math.atan2(math.sin(theta) * math.sin(delta) * math.cos(phi1),
                                   math.cos(delta) - math.sin(phi1) * math.sin(phi2))
    lon = (math.degrees(lambda2) + 540) % 360 - 180
    return Point(max(-90.0, min(90.0, math.degrees(phi2))), lon)


def random_point(rng):
    return Point(rng.uniform(-90, 90), rng.uniform(-180, 180))


def random_mbr(rng):
    lat1, lat2 = sorted(rng.uniform(-90, 90) for _ in range(2))
    lon1, lon2 = sorted(rng.uniform(-180, 180) for _ in range(2))
    return MBR(lat1, lon1, lat2, lon2)


class TestDistances(unittest.TestCase):
    def test_lima_cusco(self):
        self.assertAlmostEqual(haversine(LIMA, CUSCO) / 1000, 574.6, delta=0.5)
        self.assertAlmostEqual(haversine(LIMA, CUSCO), law_of_cosines(LIMA, CUSCO), delta=0.01)

    def test_known_values(self):
        self.assertAlmostEqual(haversine(Point(0, 0), Point(1, 0)), METERS_PER_DEGREE, places=3)
        self.assertAlmostEqual(haversine(Point(0, 0), Point(0, 1)), METERS_PER_DEGREE, places=3)
        self.assertAlmostEqual(haversine(Point(0, 0), Point(0, 180)), math.pi * EARTH_RADIUS_M, places=3)
        self.assertAlmostEqual(haversine(Point(90, 0), Point(90, 120)), 0, places=6)  # mismo polo
        self.assertAlmostEqual(euclidean(Point(0, 0), Point(3, 4)), 5 * METERS_PER_DEGREE, places=6)

    def test_metric_properties(self):
        rng = random.Random(19)
        for metric in Metric:
            for _ in range(300):
                a, b, c = random_point(rng), random_point(rng), random_point(rng)
                ab = distance(a, b, metric)
                self.assertEqual(distance(a, a, metric), 0)
                self.assertAlmostEqual(ab, distance(b, a, metric), places=6)
                self.assertLessEqual(ab, distance(a, c, metric) + distance(c, b, metric) + 1e-6)

    def test_euclidean_vs_haversine_near_lima(self):
        # Norte-sur coinciden; este-oeste la euclidiana sobreestima por 1/cos(lat).
        north = Point(LIMA.lat + 0.05, LIMA.lon)
        east = Point(LIMA.lat, LIMA.lon + 0.05)
        self.assertAlmostEqual(euclidean(LIMA, north) / haversine(LIMA, north), 1, places=6)
        self.assertAlmostEqual(euclidean(LIMA, east) / haversine(LIMA, east),
                               1 / math.cos(math.radians(LIMA.lat)), places=4)

    def test_unknown_metric(self):
        with self.assertRaises(ValueError):
            distance(LIMA, CUSCO, "manhattan")


class TestMindist(unittest.TestCase):
    def sample_mbr(self, mbr, steps=60):
        """Puntos del borde y del interior del MBR."""
        for i in range(steps + 1):
            for j in range(steps + 1):
                yield Point(mbr.min_lat + (mbr.max_lat - mbr.min_lat) * i / steps,
                            mbr.min_lon + (mbr.max_lon - mbr.min_lon) * j / steps)

    def test_zero_inside_or_on_border(self):
        mbr = MBR(-13, -78, -11, -76)
        for metric in Metric:
            self.assertEqual(mindist(LIMA, mbr, metric), 0)
            self.assertEqual(mindist(Point(-13, -77), mbr, metric), 0)

    def test_lower_bound_and_tight(self):
        rng = random.Random(18)
        for metric in Metric:
            for _ in range(150):
                mbr, p = random_mbr(rng), random_point(rng)
                bound = mindist(p, mbr, metric)
                sampled = min(distance(p, q, metric) for q in self.sample_mbr(mbr))
                # Cota inferior: nunca supera la distancia a un punto del MBR...
                self.assertLessEqual(bound, sampled + 1e-6)
                # ...y es ajustada: la diferencia es menor que el paso del muestreo.
                step = max(mbr.max_lat - mbr.min_lat, mbr.max_lon - mbr.min_lon) / 60 * METERS_PER_DEGREE
                self.assertLessEqual(sampled - bound, step + 1e-6)

    def test_across_antimeridian(self):
        mbr = MBR(-10, 170, 10, 179)
        p = Point(0, -179)  # a 2° del borde este pasando por el antimeridiano
        self.assertAlmostEqual(mindist(p, mbr), haversine(p, Point(0, 179)), places=6)


class TestRadiusToMbr(unittest.TestCase):
    def test_contains_every_point_in_the_circle(self):
        rng = random.Random(25)
        centers = [LIMA, Point(0, 0), Point(-89.9, 10), Point(60, 179.99), Point(45, -179.5)]
        centers += [random_point(rng) for _ in range(30)]
        for center in centers:
            for radius in (0, 1_000, 5_000, 10_000, 500_000):
                box = radius_to_mbr(center, radius)
                for _ in range(40):
                    q = destination(center, rng.uniform(0, 360), radius * rng.random() ** 0.5)
                    self.assertTrue(box.contains_point(q), (center, radius, q, box))

    def test_euclidean_box(self):
        box = radius_to_mbr(LIMA, 5_000, Metric.EUCLIDEAN)
        side = 5_000 / METERS_PER_DEGREE
        self.assertAlmostEqual(box.max_lat - LIMA.lat, side, places=8)
        self.assertAlmostEqual(LIMA.lon - box.min_lon, side, places=8)

    def test_haversine_box_is_tight_near_lima(self):
        box = radius_to_mbr(LIMA, 5_000)
        self.assertAlmostEqual(haversine(LIMA, Point(box.max_lat, LIMA.lon)), 5_000, delta=0.01)
        # El ancho en longitud crece con 1/cos(lat), pero no más de un 3% en Lima.
        self.assertLess(box.max_lon - LIMA.lon, 1.03 * 5_000 / METERS_PER_DEGREE)

    def test_whole_world_and_invalid_radius(self):
        self.assertEqual(radius_to_mbr(LIMA, math.pi * EARTH_RADIUS_M), MBR(-90, -180, 90, 180))
        for radius in (-1, math.nan, "5"):
            with self.assertRaises(ValueError):
                radius_to_mbr(LIMA, radius)


if __name__ == "__main__":
    unittest.main()
