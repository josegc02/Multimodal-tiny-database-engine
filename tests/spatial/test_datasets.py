import csv
import json
import tempfile
import unittest
from pathlib import Path

from benchmarks.generate_spatial_datasets import generate_points, generate_queries, main
from engine.spatial.geometry import Point, load_districts


class TestSpatialDatasets(unittest.TestCase):
    def test_deterministic(self):
        rows = generate_points(30, 25)
        self.assertEqual(rows, generate_points(30, 25))
        self.assertEqual([row["id"] for row in rows], list(range(30)))
        self.assertTrue(all(isinstance(row["ubicacion"], Point) for row in rows))
        self.assertEqual(generate_queries(5, 1), generate_queries(5, 1))

    def test_files(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            main(["--sizes", "11", "--queries", "4", "--seed", "9", "--output", str(output)])
            with (output / "puntos_11.csv").open() as stream:
                self.assertEqual(len(list(csv.DictReader(stream))), 11)
            with (output / "postgis_puntos_11.csv").open() as stream:
                self.assertEqual(len(list(csv.DictReader(stream))), 11)
            self.assertIn("USING RTREE", (output / "cargar_motor_11.sql").read_text())
            metadata = json.loads((output / "metadata.json").read_text())
            self.assertEqual(metadata["queries"], 4)

    def test_geojson(self):
        fixture = Path(__file__).parents[2] / "datasets/spatial/distritos_sinteticos_lima.geojson"
        self.assertEqual(set(load_districts(fixture)), {"Centro", "Sur"})
