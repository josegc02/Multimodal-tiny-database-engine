import csv
import io
import json
import os
import random
import struct
import tempfile
import unittest
from unittest.mock import patch

from frontend.motor import Motor
from engine.query._temp_records import read_record, write_record
from engine.query.errors import SQLParseError
from engine.query.external_algorithms import BufferConfig, ExecutionStats
from engine.query.parser import parse
from engine.query.sql_executor import SQLExecutor
from engine.spatial.distance import Metric, distance
from engine.spatial.geometry import Point
from engine.storage.record import Schema
from engine.storage.heap_file import HeapFile
from engine.storage.sequential_file import SequentialFile
from engine.storage.clustered_file import ClusteredBPlusFile

CENTER = Point(-12.0464, -77.0428)
ORIGIN = "POINT(-12.0464, -77.0428)"
POLYGON = "POLYGON((-12.1,-77.1),(-12.1,-77),(-12,-77),(-12,-77.1))"


class TestPointStorageAndParser(unittest.TestCase):
    def test_binary_round_trip_and_temporary_records(self):
        schema = Schema([("id", "int"), ("p", "point"), ("name", "str", 10), ("q", "point")])
        row = {"id": 7, "p": CENTER, "name": "Lima", "q": Point(0, 180)}
        binary = schema.serialize(row)
        self.assertEqual(len(binary), 50)
        self.assertEqual(binary[8:24], struct.pack(">dd", CENTER.lat, CENTER.lon))
        self.assertEqual(schema.deserialize(binary), row)
        stream = io.BytesIO()
        write_record(stream, row)
        stream.seek(0)
        self.assertEqual(read_record(stream), row)
        with self.assertRaises(ValueError):
            schema.serialize({**row, "p": (-12, -77)})

    def test_point_persists_in_all_storages(self):
        schema = [("id", "int"), ("p", "point")]
        with tempfile.TemporaryDirectory() as directory:
            factories = [lambda: HeapFile(os.path.join(directory, "heap"), schema),
                         lambda: SequentialFile(os.path.join(directory, "main"), os.path.join(directory, "aux"), schema, key_field="id"),
                         lambda: ClusteredBPlusFile(os.path.join(directory, "bpt"), schema, key_field="id")]
            for factory in factories:
                storage = factory()
                storage.insert({"id": 1, "p": CENTER})
                storage.close()
                reopened = factory()
                try:
                    self.assertEqual([row for _, row in reopened.scan()], [{"id": 1, "p": CENTER}])
                finally:
                    reopened.close()

    def test_parser_ast_and_rejections(self):
        statement = parse(f"SELECT distancia(p,{ORIGIN}) AS d FROM t ORDER BY d LIMIT 10 USING EUCLIDEAN")
        self.assertEqual(statement.columns[0].expression.metric, "euclidean")
        long_filter = " AND ".join(["id > 0"] * 1200)
        long_statement = parse(f"SELECT distancia(p,{ORIGIN}) FROM t WHERE {long_filter} USING EUCLIDEAN")
        self.assertEqual(long_statement.columns[0].expression.metric, "euclidean")
        json.dumps(statement.to_dict())
        json.dumps(parse(f"SELECT * FROM t WHERE WITHIN(p,{POLYGON})").to_dict())
        for sql in ["CREATE TABLE t (p POINT(2))", "SELECT * FROM t WHERE distancia(p)",
                    "INSERT INTO t VALUES (POINT(91, 0))", "INSERT INTO t VALUES (POINT('x', 0))",
                    "INSERT INTO t VALUES (POINT(0, 0, 0))", "SELECT * FROM t USING MANHATTAN",
                    "SELECT distancia(p, POINT(0,0), 'bad') FROM t",
                    "SELECT * FROM t WHERE WITHIN(p, POLYGON((0,0),(1,1)))"]:
            with self.subTest(sql=sql), self.assertRaises(SQLParseError):
                parse(sql)


class TestSpatialSQL(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        patcher = patch("frontend.motor.DEMO_DIR", self.temp.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.motor = Motor()
        self.addCleanup(self.motor.cerrar)
        self.run_sql("CREATE TABLE tiendas (id INT PRIMARY KEY, ubicacion POINT, categoria INT)")
        rng = random.Random(23)
        self.points = [Point(round(rng.uniform(-12.3, -11.8), 6), round(rng.uniform(-77.3, -76.8), 6)) for _ in range(230)]
        self.points += [CENTER, CENTER, Point(-12.1, -77.1), Point(-12, -77)]
        values = ",".join(f"({i},POINT({p.lat},{p.lon}),{i % 3})" for i, p in enumerate(self.points))
        self.run_sql(f"INSERT INTO tiendas VALUES {values}")

    def run_sql(self, sql):
        result = self.motor.ejecutar(sql)
        self.assertFalse(result.tiene_error, f"{sql}\n{result.error}")
        return result

    def indexed(self):
        self.run_sql("CREATE INDEX geo ON tiendas (ubicacion) USING RTREE")
        return self.motor.catalog.table("tiendas").indexes["ubicacion"].index

    def test_radius_polygon_and_boolean_filters_match_scan(self):
        queries = []
        for metric in ("HAVERSINE", "EUCLIDEAN"):
            for predicate in [f"distancia(ubicacion,{ORIGIN}) < 5000",
                              f"5000 >= distancia({ORIGIN},ubicacion)",
                              f"distancia(ubicacion,{ORIGIN}) <= 0",
                              f"distancia(ubicacion,{ORIGIN}) < -1",
                              f"distancia(ubicacion,{ORIGIN}) < 5000 AND categoria = 1",
                              f"distancia(ubicacion,{ORIGIN}) < 5000 OR categoria = 1",
                              f"NOT distancia(ubicacion,{ORIGIN}) < 5000",
                              f"WITHIN(ubicacion,{POLYGON})",
                              f"WITHIN(ubicacion,{POLYGON}) AND categoria = 2"]:
                queries.append(f"SELECT id,ubicacion FROM tiendas WHERE {predicate} ORDER BY id USING {metric}")
        expected = [self.run_sql(q).filas for q in queries]
        self.indexed()
        for q, rows in zip(queries, expected):
            self.assertEqual(self.run_sql(q).filas, rows, q)
        actual = self.run_sql(f"SELECT id FROM tiendas WHERE distancia(ubicacion,{ORIGIN}) < 5000 ORDER BY id").filas
        self.assertEqual(actual, [(i,) for i, p in enumerate(self.points) if distance(p, CENTER) < 5000])

    def test_knn_filters_offset_metrics_and_aliases(self):
        self.indexed()
        for metric in Metric:
            for condition in ["id >= 0", "categoria = 2", "id < 0", "id < 5"]:
                allowed = [i for i in range(len(self.points)) if
                           (condition == "id >= 0" or condition == "categoria = 2" and i % 3 == 2
                            or condition == "id < 5" and i < 5)]
                ordered = sorted(allowed, key=lambda i: (distance(CENTER, self.points[i], metric), i))
                for k, offset in [(0, 0), (1, 0), (10, 3), (500, 0), (5, 999)]:
                    q = (f"SELECT id,distancia(ubicacion,{ORIGIN}) AS metros FROM tiendas WHERE {condition} "
                         f"ORDER BY metros LIMIT {k} OFFSET {offset} USING {metric.value}")
                    self.assertEqual(self.run_sql(q).filas,
                                     [(i, distance(self.points[i], CENTER, metric)) for i in ordered[offset:offset + k]])

    def test_knn_fallback_for_secondary_sort_distinct_group_and_join(self):
        queries = [
            f"SELECT id FROM tiendas ORDER BY distancia(ubicacion,{ORIGIN}), id DESC LIMIT 10",
            f"SELECT id FROM tiendas ORDER BY distancia(ubicacion,{ORIGIN}) DESC LIMIT 10",
            f"SELECT DISTINCT distancia(ubicacion,{ORIGIN}) AS d FROM tiendas ORDER BY d LIMIT 10",
            f"SELECT categoria, MIN(distancia(ubicacion,{ORIGIN})) AS d FROM tiendas GROUP BY categoria ORDER BY d LIMIT 2",
            f"SELECT t.id FROM tiendas t JOIN cuentas c ON t.categoria=c.id ORDER BY distancia(t.ubicacion,{ORIGIN}), t.id LIMIT 10"]
        expected = [self.run_sql(q).filas for q in queries]
        self.indexed()
        for q, rows in zip(queries, expected):
            self.assertEqual(self.run_sql(q).filas, rows)

    def test_metric_override_dynamic_centers_and_point_equality(self):
        q = (f"SELECT id,distancia(ubicacion,{ORIGIN},'euclidean') AS d FROM tiendas "
             "ORDER BY d LIMIT 10 USING HAVERSINE")
        expected = self.run_sql(q).filas
        ordered = sorted(range(len(self.points)), key=lambda i: (distance(self.points[i], CENTER, Metric.EUCLIDEAN), i))[:10]
        self.assertEqual(expected, [(i, distance(self.points[i], CENTER, Metric.EUCLIDEAN)) for i in ordered])
        self.indexed()
        self.assertEqual(self.run_sql(q).filas, expected)
        self.assertEqual(self.run_sql(f"SELECT id FROM tiendas WHERE ubicacion={ORIGIN} ORDER BY id").filas,
                         [(i,) for i, p in enumerate(self.points) if p == CENTER])
        # Un centro por fila no permite elegir un único recorrido del R-Tree.
        dynamic = "SELECT id,distancia(ubicacion,ubicacion) AS d FROM tiendas ORDER BY d,id LIMIT 3"
        self.assertEqual(self.run_sql(dynamic).filas, [(0, 0.0), (1, 0.0), (2, 0.0)])

    def test_copy_invalid_point_is_atomic_and_reports_line(self):
        self.indexed()
        before = self.run_sql("SELECT COUNT(*) FROM tiendas").filas
        path = os.path.join(self.temp.name, "invalid.csv")
        with open(path, "w", newline="", encoding="utf-8") as stream:
            csv.writer(stream).writerows([[1000, ORIGIN, 1], [1001, "POINT(91,0)", 1]])
        result = self.motor.ejecutar(f"COPY tiendas FROM '{path.replace(os.sep, '/')}';")
        self.assertTrue(result.tiene_error)
        self.assertIn("línea 2", result.error)
        self.assertEqual(self.run_sql("SELECT COUNT(*) FROM tiendas").filas, before)

    def test_optimizer_really_uses_index_and_stale_index_falls_back(self):
        self.indexed()
        binding = self.motor.catalog.table("tiendas")
        queries = [f"SELECT * FROM tiendas WHERE distancia(ubicacion,{ORIGIN}) < 5000",
                   f"SELECT * FROM tiendas WHERE WITHIN(ubicacion,{POLYGON})",
                   f"SELECT * FROM tiendas ORDER BY distancia(ubicacion,{ORIGIN}) LIMIT 10"]
        # El mapa lee la tabla una vez y la cachea; se calienta antes para que el
        # test verifique solo el acceso de la consulta.
        self.run_sql(queries[0])
        with patch.object(binding.storage, "scan", side_effect=AssertionError("No debe escanear")):
            for q in queries:
                self.run_sql(q)
        binding.indexes["ubicacion"].valid = False
        with patch.object(binding.indexes["ubicacion"].index, "knn", side_effect=AssertionError("Índice inválido")):
            self.assertEqual(len(self.run_sql(queries[-1]).filas), 10)

    def test_explain_analyze_counters_and_no_execution_for_explain(self):
        tree = self.indexed()
        for clause, method in [(f"WHERE distancia(ubicacion,{ORIGIN}) < 5000", "range_query"),
                               (f"WHERE WITHIN(ubicacion,{POLYGON})", "within_polygon"),
                               (f"ORDER BY distancia(ubicacion,{ORIGIN}) LIMIT 10", "knn")]:
            q = f"SELECT * FROM tiendas {clause}"
            with patch.object(tree, method, side_effect=AssertionError("EXPLAIN no ejecuta")):
                text = "\n".join(self.run_sql("EXPLAIN " + q).plan)
                self.assertIn("using geo", text)
                self.assertNotIn("Nodes Visited:", text)
            result = self.run_sql("EXPLAIN ANALYZE " + q)
            text = "\n".join(result.plan)
            self.assertIn("Nodes Visited:", text)
            self.assertIn("Exact Refinements:", text)
            self.assertTrue(any("Nodes Visited:" in detail for node in result.plan_nodos for detail in node["details"]))

    def test_rollback_delete_insert_copy_and_index_maintenance(self):
        tree = self.indexed()
        q = f"SELECT id FROM tiendas WHERE distancia(ubicacion,{ORIGIN}) < 5000 ORDER BY id"
        expected = self.run_sql(q).filas
        self.run_sql(f"BEGIN; DELETE FROM tiendas WHERE WITHIN(ubicacion,{POLYGON}); "
                     f"INSERT INTO tiendas VALUES (1000,{ORIGIN},1); ROLLBACK")
        self.assertEqual(self.run_sql(q).filas, expected)
        self.assertEqual(len(tree), len(self.points))
        bad = self.motor.ejecutar(f"INSERT INTO tiendas VALUES (1001,{ORIGIN},1), (0,{ORIGIN},1)")
        self.assertTrue(bad.tiene_error)
        self.assertEqual(self.run_sql(q).filas, expected)
        path = os.path.join(self.temp.name, "points.csv")
        with open(path, "w", newline="", encoding="utf-8") as stream:
            csv.writer(stream).writerow([1002, ORIGIN, 2])
        self.run_sql(f"COPY tiendas FROM '{path.replace(os.sep, '/')}';")
        self.assertIn((1002,), self.run_sql(q).filas)
        self.run_sql("DELETE FROM tiendas WHERE id=1002")
        self.assertEqual(self.run_sql(q).filas, expected)

    def test_points_in_external_sort_group_distinct_and_join(self):
        executor = SQLExecutor(self.motor.catalog, BufferConfig(buffer_pages=3, records_per_page=2))
        queries = ["SELECT * FROM tiendas ORDER BY id DESC",
                   "SELECT DISTINCT ubicacion FROM tiendas ORDER BY ubicacion",
                   "SELECT ubicacion, COUNT(*) AS n FROM tiendas GROUP BY ubicacion ORDER BY ubicacion",
                   "SELECT t.id,t.ubicacion FROM tiendas t JOIN cuentas c ON t.categoria=c.id ORDER BY t.id"]
        for q in queries:
            expected = self.run_sql(q).filas
            stats = ExecutionStats()
            rows = list(executor.execute(q, stats=stats))
            self.assertEqual([tuple(row.values()) for row in rows], expected)
            self.assertGreater(stats.records_written, 0)

    def test_sequential_and_clustered_spatial_indexes_survive_rid_changes(self):
        for method in ("SEQUENTIAL", "BTREE"):
            table = "t_" + method.lower()
            self.run_sql(f"CREATE TABLE {table} (id INT PRIMARY KEY, p POINT) USING {method}")
            self.run_sql(f"CREATE INDEX idx_{table} ON {table} (p) USING RTREE")
            for i in (10, 3, 8, 1, 9):
                self.run_sql(f"INSERT INTO {table} VALUES ({i},POINT(0,{i}))")
            q = f"SELECT id FROM {table} ORDER BY distancia(p,POINT(0,0)) LIMIT 3"
            self.assertEqual(self.run_sql(q).filas, [(1,), (3,), (8,)])
            self.run_sql(f"BEGIN; DELETE FROM {table} WHERE id=1; INSERT INTO {table} VALUES (2,POINT(0,2)); ROLLBACK")
            self.assertEqual(self.run_sql(q).filas, [(1,), (3,), (8,)])

    def test_validation_even_empty_and_empty_result_headers(self):
        self.run_sql("CREATE TABLE vacia (id INT, p POINT)")
        for sql in ["SELECT * FROM vacia WHERE distancia(id,POINT(0,0)) < 1",
                    "SELECT * FROM vacia WHERE WITHIN(p,POINT(0,0))",
                    "CREATE INDEX bad ON vacia (id) USING RTREE",
                    "CREATE INDEX bad ON vacia (p) USING BTREE",
                    "INSERT INTO vacia VALUES (1,'POINT(0,0)')",
                    "CREATE TABLE bad (p POINT PRIMARY KEY)"]:
            self.assertTrue(self.motor.ejecutar(sql).tiene_error, sql)
        result = self.run_sql("SELECT id,p FROM vacia ORDER BY distancia(p,POINT(0,0)) LIMIT 10")
        self.assertEqual(result.columnas, ["id", "p"])
        self.assertEqual(result.filas, [])
        self.assertTrue(result.tiene_tabla)
