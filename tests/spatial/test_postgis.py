import unittest

from engine.spatial.geometry import Point
from postgis.client import point_params


class TestPostGISAdapter(unittest.TestCase):
    def test_coordinates_are_converted_to_lon_lat(self):
        self.assertEqual(point_params(Point(-12.0464, -77.0428)), (-77.0428, -12.0464))

    def test_point_params_requires_point(self):
        with self.assertRaises(TypeError):
            point_params((-12.0, -77.0))
