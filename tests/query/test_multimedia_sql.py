import os
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from engine.query.errors import SQLSemanticError
from engine.query.logical_plan import LogicalPlanner
from engine.query.parser import parse
from frontend.motor import Motor

# Vectores conocidos por ruta: el extractor real (SIFT/MFCC) se prueba en test_multimedia_e2e.
VECTORS = {
    "img/gato.jpg": [1.0, 0.0, 0.0],
    "img/gato2.jpg": [0.9, 0.1, 0.0],
    "img/perro.jpg": [0.0, 1.0, 0.0],
    "img/perro2.jpg": [0.1, 0.9, 0.1],
    "img/ave.jpg": [0.0, 0.0, 1.0],
    "img/pez.jpg": [0.3, 0.3, 0.9],
    "img/consulta.jpg": [0.96, 0.04, 0.0],
    "aud/a.wav": [1.0, 2.0],
    "aud/b.wav": [2.0, 1.0],
}


def fake_extract(kind, path):
    if path not in VECTORS:
        raise FileNotFoundError(f"Archivo no encontrado: {path}")
    return np.asarray(VECTORS[path], dtype=np.float32)


class MultimediaSQLTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        for target, value in (("frontend.motor.DEMO_DIR", self.temp_dir.name),
                              ("engine.storage.media_store.extract_features", fake_extract)):
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.motor = Motor()
        self.addCleanup(self.motor.cerrar)

    def execute(self, sql):
        result = self.motor.ejecutar(sql)
        self.assertFalse(result.tiene_error, result.error)
        return result

    def explain(self, sql):
        return "\n".join(str(row[0]) for row in self.execute(sql).filas)

    def fails(self, sql):
        result = self.motor.ejecutar(sql)
        self.assertTrue(result.tiene_error, f"Se esperaba un error: {sql}")
        return result.error


class TestMediaColumns(MultimediaSQLTestCase):
    def test_insert_stores_the_path_and_extracts_the_vector(self):
        self.execute("CREATE TABLE fotos (id INT PRIMARY KEY, nombre VARCHAR(20), foto IMAGE, sonido AUDIO)")
        self.execute("INSERT INTO fotos VALUES (1, 'gato', 'img/gato.jpg', 'aud/a.wav'), "
                     "(2, 'perro', 'img/perro.jpg', 'aud/b.wav')")
        self.assertEqual(self.execute("SELECT id, foto, sonido FROM fotos WHERE foto = 'img/perro.jpg'").filas,
                         [(2, "img/perro.jpg", "aud/b.wav")])
        schema = self.motor.catalog.table("fotos").storage.schema
        np.testing.assert_allclose(schema.vector("foto", "img/gato.jpg"), VECTORS["img/gato.jpg"])
        np.testing.assert_allclose(schema.vector("sonido", "aud/b.wav"), VECTORS["aud/b.wav"])
        self.assertTrue(os.path.exists(os.path.join(self.temp_dir.name, "fotos.media")))

    def test_missing_file_rejects_the_insert(self):
        self.execute("CREATE TABLE fotos (id INT, foto IMAGE)")
        self.assertIn("no_existe.jpg", self.fails("INSERT INTO fotos VALUES (1, 'no_existe.jpg')"))
        self.assertEqual(self.execute("SELECT COUNT(*) FROM fotos").filas, [(0,)])

    def test_every_storage_keeps_media_columns(self):
        for method in ("HEAP", "SEQUENTIAL", "BTREE"):
            with self.subTest(method=method):
                table = f"t_{method.lower()}"
                self.execute(f"CREATE TABLE {table} (id INT PRIMARY KEY, foto IMAGE) USING {method}")
                self.execute(f"INSERT INTO {table} VALUES (2, 'img/ave.jpg'), (1, 'img/gato.jpg')")
                self.assertEqual(self.execute(f"SELECT id, foto FROM {table} ORDER BY id").filas,
                                 [(1, "img/gato.jpg"), (2, "img/ave.jpg")])

    def test_image_and_audio_are_not_reserved_words(self):
        self.execute("CREATE TABLE medios (image IMAGE, audio AUDIO, id INT)")
        self.execute("INSERT INTO medios VALUES ('img/pez.jpg', 'aud/a.wav', 1)")
        self.assertEqual(self.execute("SELECT image, audio FROM medios").filas, [("img/pez.jpg", "aud/a.wav")])

    def test_media_columns_cannot_be_keys(self):
        self.execute("CREATE TABLE padre (id INT PRIMARY KEY)")
        for sql in ("CREATE TABLE a (foto IMAGE PRIMARY KEY)",
                    "CREATE TABLE b (sonido AUDIO, id INT) USING SEQUENTIAL",
                    "CREATE TABLE c (id INT, foto IMAGE REFERENCES padre)",
                    "CREATE TABLE d (foto IMAGE(10))"):
            with self.subTest(sql=sql):
                self.fails(sql)

    def test_media_columns_require_a_path(self):
        self.execute("CREATE TABLE fotos (id INT, foto IMAGE)")
        for value in ("1", "''", "POINT(1, 2)"):
            with self.subTest(value=value):
                self.fails(f"INSERT INTO fotos VALUES (1, {value})")

    def test_copy_loads_media_columns(self):
        path = os.path.join(self.temp_dir.name, "fotos.csv")
        with open(path, "w", encoding="utf-8") as stream:
            stream.write("id,foto\n1, img/gato.jpg\n2,img/perro.jpg\n")
        self.execute("CREATE TABLE fotos (id INT, foto IMAGE)")
        self.execute(f"COPY fotos FROM '{path}' WITH (FORMAT csv, HEADER true)")
        self.assertEqual(self.execute("SELECT foto FROM fotos ORDER BY id").filas,
                         [("img/gato.jpg",), ("img/perro.jpg",)])

    def test_media_columns_only_admit_vector_indexes(self):
        self.execute("CREATE TABLE fotos (id INT, foto IMAGE)")
        for method in ("HASH", "BTREE", "SPIMI"):
            with self.subTest(method=method):
                self.fails(f"CREATE INDEX i ON fotos (foto) USING {method}")


class TestVectorIndexes(MultimediaSQLTestCase):
    def setUp(self):
        super().setUp()
        self.execute("CREATE TABLE fotos (id INT PRIMARY KEY, nombre VARCHAR(20), foto IMAGE, sonido AUDIO)")
        self.execute("INSERT INTO fotos VALUES (1, 'gato', 'img/gato.jpg', 'aud/a.wav'), "
                     "(2, 'perro', 'img/perro.jpg', 'aud/b.wav')")

    def registered(self, column):
        return self.motor.catalog.table("fotos").indexes[column]

    def test_create_hnsw_and_ivf_indexes(self):
        self.execute("CREATE INDEX fotos_hnsw ON fotos USING HNSW (foto) WITH (METRIC = cosine)")
        self.execute("CREATE INDEX sonido_ivf ON fotos (sonido) USING IVF")
        foto, sonido = self.registered("foto"), self.registered("sonido")
        self.assertTrue(foto.metadata.vector and foto.valid)
        self.assertEqual((foto.index.method, foto.index.metric, foto.index.size), ("hnsw", "cosine", 2))
        self.assertEqual((sonido.index.method, sonido.index.metric), ("ivf", "euclidean"))

    def test_index_follows_inserts_and_deletes(self):
        self.execute("CREATE INDEX fotos_hnsw ON fotos (foto) USING HNSW")
        self.execute("INSERT INTO fotos VALUES (3, 'ave', 'img/ave.jpg', 'aud/a.wav')")
        self.execute("DELETE FROM fotos WHERE id = 1")
        index = self.registered("foto").index
        storage = self.motor.catalog.table("fotos").storage
        found = [storage.get(rid)["id"] for rid, _ in index.knn(VECTORS["img/gato.jpg"], 5).matches]
        self.assertEqual(sorted(found), [2, 3])

    def test_equality_on_a_media_column_does_not_use_the_vector_index(self):
        self.execute("CREATE INDEX fotos_ivf ON fotos (foto) USING IVF")
        self.assertEqual(self.execute("SELECT id FROM fotos WHERE foto = 'img/perro.jpg'").filas, [(2,)])
        self.assertIn("Seq Scan", self.explain("EXPLAIN SELECT id FROM fotos WHERE foto = 'img/perro.jpg'"))

    def test_vector_indexes_require_media_columns(self):
        for sql in ("CREATE INDEX i ON fotos USING HNSW (nombre)",
                    "CREATE INDEX i ON fotos (nombre) USING IVF WITH (METRIC = 'dot')"):
            with self.subTest(sql=sql):
                self.assertIn("IMAGE o AUDIO", self.fails(sql))

    def test_close_writes_the_index_file(self):
        self.execute("CREATE INDEX fotos_hnsw ON fotos (foto) USING HNSW")
        self.motor.cerrar()
        self.assertTrue(os.path.exists(os.path.join(self.temp_dir.name, "fotos_fotos_hnsw.hnsw")))


class TestPlanner(MultimediaSQLTestCase):
    SIMILAR = "SIMILAR_TO('img/consulta.jpg', k=3) USING HNSW"

    def setUp(self):
        super().setUp()
        self.execute("CREATE TABLE fotos (id INT PRIMARY KEY, anio INT, foto IMAGE, otra IMAGE, sonido AUDIO)")
        self.execute("CREATE INDEX fotos_foto ON fotos (foto) USING HNSW WITH (METRIC = cosine)")
        self.execute("CREATE INDEX fotos_sonido ON fotos (sonido) USING IVF")

    def plan(self, sql):
        return LogicalPlanner(self.motor.catalog).plan(parse(sql))

    def scan(self, plan):
        while plan.operation != "Scan":
            plan = plan.children[0]
        return plan

    def operations(self, plan):
        return [plan.operation] + [name for child in plan.children for name in self.operations(child)]

    def vector_k(self, tail, columns="*", where=""):
        return self.scan(self.plan(f"SELECT {columns} FROM fotos WHERE {self.SIMILAR} {where} {tail}")).get("vector_k")

    def test_similar_to_goes_to_the_scan_with_its_column_and_metric(self):
        plan = self.plan(f"SELECT * FROM fotos WHERE {self.SIMILAR}")
        search = self.scan(plan).get("vector_search")
        self.assertEqual((search.column.name, search.method, search.metric, search.k), ("foto", "hnsw", "cosine", 3))
        self.assertNotIn("Filter", self.operations(plan))

    def test_explicit_column_and_audio_index(self):
        search = self.scan(self.plan("SELECT * FROM fotos AS f WHERE SIMILAR_TO(f.sonido, 'aud/a.wav', k=2) "
                                     "USING IVF WITH METRIC=euclidean")).get("vector_search")
        self.assertEqual((search.column.name, search.column.table, search.metric), ("sonido", "f", "euclidean"))

    def test_other_conditions_stay_in_the_where(self):
        plan = self.plan(f"SELECT * FROM fotos WHERE anio > 2000 AND {self.SIMILAR}")
        self.assertIn("Filter", self.operations(plan))
        self.assertIsNotNone(self.scan(plan).get("vector_search"))

    def test_order_by_similarity_needs_no_sort(self):
        for tail in ("ORDER BY SIMILARITY_SCORE() DESC", "ORDER BY score DESC"):
            with self.subTest(tail=tail):
                plan = self.plan(f"SELECT id, SIMILARITY_SCORE() AS score FROM fotos WHERE {self.SIMILAR} {tail}")
                self.assertNotIn("Sort", self.operations(plan))
        plan = self.plan(f"SELECT * FROM fotos WHERE {self.SIMILAR} ORDER BY SIMILARITY_SCORE() ASC")
        self.assertIn("Sort", self.operations(plan))

    def test_limit_reduces_k_only_when_it_cannot_lose_rows(self):
        self.assertEqual(self.vector_k(""), 3)
        self.assertEqual(self.vector_k("LIMIT 2"), 2)
        self.assertEqual(self.vector_k("LIMIT 5"), 3)
        self.assertEqual(self.vector_k("LIMIT 1 OFFSET 1"), 2)
        self.assertEqual(self.vector_k("ORDER BY SIMILARITY_SCORE() DESC LIMIT 1"), 1)
        self.assertEqual(self.vector_k("ORDER BY id LIMIT 1"), 3)
        self.assertEqual(self.vector_k("LIMIT 1", where="AND anio > 1"), 3)
        self.assertEqual(self.vector_k("LIMIT 1", columns="DISTINCT anio"), 3)

    def test_rejected_queries(self):
        for sql in (f"SELECT * FROM fotos WHERE {self.SIMILAR} OR anio = 1",
                    f"SELECT * FROM fotos WHERE NOT {self.SIMILAR}",
                    f"SELECT * FROM fotos WHERE {self.SIMILAR} AND {self.SIMILAR}",
                    f"SELECT * FROM fotos f JOIN fotos g ON f.id = g.id WHERE {self.SIMILAR}",
                    "SELECT * FROM fotos WHERE SIMILAR_TO('q', k=3) USING IVF WITH METRIC=cosine",
                    "SELECT * FROM fotos WHERE SIMILAR_TO('q', k=3) USING HNSW WITH METRIC=dot",
                    "SELECT * FROM fotos WHERE SIMILAR_TO(otra, 'q', k=3) USING HNSW",
                    "SELECT * FROM fotos WHERE SIMILAR_TO(sonido, 'q', k=3) USING HNSW",
                    "SELECT * FROM fotos WHERE SIMILAR_TO(anio, 'q', k=3) USING HNSW",
                    "SELECT * FROM fotos WHERE SIMILAR_TO(nada, 'q', k=3) USING HNSW",
                    "SELECT SIMILARITY_SCORE() FROM fotos",
                    "SELECT * FROM fotos ORDER BY SIMILARITY_SCORE() DESC",
                    "DELETE FROM fotos WHERE SIMILARITY_SCORE() > 0.5",
                    f"DELETE FROM fotos WHERE {self.SIMILAR}",
                    f"SELECT COUNT(*), SIMILARITY_SCORE() FROM fotos WHERE {self.SIMILAR}",
                    f"SELECT MAX(SIMILARITY_SCORE()) FROM fotos WHERE {self.SIMILAR}"):
            with self.subTest(sql=sql), self.assertRaises(SQLSemanticError):
                self.plan(sql)

    def test_table_without_or_with_several_indexes_of_that_method(self):
        self.execute("CREATE TABLE sin (id INT, foto IMAGE)")
        with self.assertRaisesRegex(SQLSemanticError, "no tiene"):
            self.plan("SELECT * FROM sin WHERE SIMILAR_TO('q', k=1) USING HNSW")
        self.execute("CREATE INDEX fotos_otra ON fotos (otra) USING HNSW WITH (METRIC = cosine)")
        with self.assertRaisesRegex(SQLSemanticError, "más de una"):
            self.plan(f"SELECT * FROM fotos WHERE {self.SIMILAR}")
        search = self.scan(self.plan("SELECT * FROM fotos WHERE SIMILAR_TO(otra, 'q', k=1) USING HNSW")).get("vector_search")
        self.assertEqual(search.column.name, "otra")

    def test_cannot_combine_with_match(self):
        self.execute("CREATE TABLE mixta (id INT, texto TEXT, foto IMAGE)")
        self.execute("CREATE INDEX mixta_texto ON mixta (texto) USING SPIMI")
        self.execute("CREATE INDEX mixta_foto ON mixta (foto) USING HNSW")
        with self.assertRaisesRegex(SQLSemanticError, "combinar"):
            self.plan("SELECT * FROM mixta WHERE MATCH(texto, 'gato') USING BM25 "
                      "AND SIMILAR_TO('q', k=1) USING HNSW")


def brute_force(query, paths, metric):
    """SIMILARITY_SCORE exacto de cada ruta, de mayor a menor."""
    query = np.asarray(VECTORS[query])

    def score(path):
        vector = np.asarray(VECTORS[path])
        if metric == "euclidean":
            return 1 / (1 + np.linalg.norm(vector - query))
        product = float(vector @ query)
        return product / (np.linalg.norm(vector) * np.linalg.norm(query)) if metric == "cosine" else product
    return sorted(((path, score(path)) for path in paths), key=lambda item: -item[1])


class MediaRowsTestCase(MultimediaSQLTestCase):
    IMAGES = [(1, "gato", 2001, "img/gato.jpg"), (2, "gato pardo", 2005, "img/gato2.jpg"),
              (3, "perro", 2010, "img/perro.jpg"), (4, "perro grande", 2015, "img/perro2.jpg"),
              (5, "ave", 2020, "img/ave.jpg"), (6, "pez", 2025, "img/pez.jpg")]
    SIMILAR = "SIMILAR_TO('img/consulta.jpg', k={k}) USING HNSW"

    def create(self, method="HNSW", metric="cosine", storage="HEAP"):
        self.execute("CREATE TABLE imagenes (id INT PRIMARY KEY, nombre VARCHAR(20), anio INT, foto IMAGE) "
                     f"USING {storage}")
        self.execute(f"CREATE INDEX imagenes_foto ON imagenes (foto) USING {method} WITH (METRIC = {metric})")
        values = ", ".join(str(row) for row in self.IMAGES)
        self.execute(f"INSERT INTO imagenes VALUES {values}")

    def paths(self):
        return [row[3] for row in self.IMAGES]

    def neighbors(self, metric="cosine"):
        by_path = {row[3]: row for row in self.IMAGES}
        return [by_path[path] for path, _ in brute_force("img/consulta.jpg", self.paths(), metric)]

    def rows(self, sql):
        return self.execute(sql).filas


class TestExecution(MediaRowsTestCase):
    def setUp(self):
        super().setUp()
        self.create()

    def test_examples_of_the_project_statement(self):
        rows = self.rows("SELECT * FROM imagenes WHERE SIMILAR_TO('img/consulta.jpg', k=3) "
                         "USING HNSW WITH METRIC=cosine;")
        self.assertEqual(rows, self.neighbors()[:3])
        self.execute("CREATE TABLE canciones (id INT, nombre VARCHAR(20), artista VARCHAR(20), audio AUDIO)")
        self.execute("CREATE INDEX canciones_audio ON canciones (audio) USING IVF WITH (METRIC = euclidean)")
        self.execute("INSERT INTO canciones VALUES (1, 'uno', 'A', 'aud/a.wav'), (2, 'dos', 'B', 'aud/b.wav')")
        rows = self.rows("SELECT nombre, artista, SIMILARITY_SCORE() as score FROM canciones "
                         "WHERE SIMILAR_TO('aud/b.wav', k=5) USING IVF WITH METRIC=euclidean ORDER BY score DESC")
        self.assertEqual([row[:2] for row in rows], [("dos", "B"), ("uno", "A")])
        self.assertAlmostEqual(rows[0][2], 1.0)
        self.assertAlmostEqual(rows[1][2], 1 / (1 + np.sqrt(2)), places=6)

    def test_scores_match_brute_force(self):
        rows = self.rows(f"SELECT foto, SIMILARITY_SCORE() FROM imagenes WHERE {self.SIMILAR.format(k=6)}")
        expected = brute_force("img/consulta.jpg", self.paths(), "cosine")
        self.assertEqual([row[0] for row in rows], [path for path, _ in expected])
        for (_, score), (_, value) in zip(rows, expected):
            self.assertAlmostEqual(score, value, places=6)

    def test_k_larger_than_the_table(self):
        self.assertEqual(len(self.rows(f"SELECT * FROM imagenes WHERE {self.SIMILAR.format(k=50)}")), 6)

    def test_query_with_an_inserted_file_finds_itself_first(self):
        rows = self.rows("SELECT id, SIMILARITY_SCORE() FROM imagenes "
                         "WHERE SIMILAR_TO('img/perro.jpg', k=1) USING HNSW")
        self.assertEqual(rows[0][0], 3)
        self.assertAlmostEqual(rows[0][1], 1.0, places=6)

    def test_other_filters_apply_to_the_k_neighbors(self):
        rows = self.rows(f"SELECT id FROM imagenes WHERE anio >= 2005 AND {self.SIMILAR.format(k=3)}")
        self.assertEqual(rows, [(row[0],) for row in self.neighbors()[:3] if row[2] >= 2005])

    def test_limit_and_other_orders(self):
        ids = [(row[0],) for row in self.neighbors()[:4]]
        similar = self.SIMILAR.format(k=4)
        self.assertEqual(self.rows(f"SELECT id FROM imagenes WHERE {similar} LIMIT 2"), ids[:2])
        self.assertEqual(self.rows(f"SELECT id FROM imagenes WHERE {similar} ORDER BY id"), sorted(ids))
        self.assertEqual(self.rows(f"SELECT id FROM imagenes WHERE {similar} ORDER BY SIMILARITY_SCORE() ASC"),
                         ids[::-1])

    def test_score_can_be_used_in_conditions_and_expressions(self):
        rows = self.rows("SELECT id, SIMILARITY_SCORE() * 100 AS pct FROM imagenes "
                         f"WHERE {self.SIMILAR.format(k=6)} AND SIMILARITY_SCORE() > 0.9")
        expected = [score for _, score in brute_force("img/consulta.jpg", self.paths(), "cosine") if score > 0.9]
        self.assertEqual(len(rows), len(expected))
        self.assertTrue(all(row[1] > 90 for row in rows))

    def test_aggregates_count_the_neighbors(self):
        self.assertEqual(self.rows(f"SELECT COUNT(*) FROM imagenes WHERE {self.SIMILAR.format(k=4)}"), [(4,)])

    def test_results_follow_inserts_and_deletes(self):
        perro = "SIMILAR_TO('img/perro.jpg', k={k}) USING HNSW"
        self.execute("DELETE FROM imagenes WHERE id = 3")
        self.assertNotIn((3,), self.rows(f"SELECT id FROM imagenes WHERE {perro.format(k=6)}"))
        self.execute("INSERT INTO imagenes VALUES (7, 'perro otra vez', 2026, 'img/perro.jpg')")
        self.assertEqual(self.rows(f"SELECT id FROM imagenes WHERE {perro.format(k=1)}"), [(7,)])

    def test_rollback_removes_the_row_from_the_results(self):
        self.execute("BEGIN")
        self.execute("INSERT INTO imagenes VALUES (8, 'consulta', 2026, 'img/consulta.jpg')")
        self.assertEqual(self.rows(f"SELECT id FROM imagenes WHERE {self.SIMILAR.format(k=1)}"), [(8,)])
        self.execute("ROLLBACK")
        self.assertNotIn((8,), self.rows(f"SELECT id FROM imagenes WHERE {self.SIMILAR.format(k=6)}"))

    def test_missing_query_file(self):
        error = self.fails("SELECT * FROM imagenes WHERE SIMILAR_TO('img/no_existe.jpg', k=3) USING HNSW")
        self.assertIn("img/no_existe.jpg", error)

    def test_query_vector_with_another_dimension(self):
        error = self.fails("SELECT * FROM imagenes WHERE SIMILAR_TO('aud/a.wav', k=3) USING HNSW")
        self.assertIn("dimensiones", error)


class TestEveryIndexAndStorage(MediaRowsTestCase):
    def reset(self):
        self.motor.cerrar()
        for name in os.listdir(self.temp_dir.name):
            os.remove(os.path.join(self.temp_dir.name, name))
        self.motor = Motor()
        self.addCleanup(self.motor.cerrar)

    def test_every_combination_returns_the_exact_neighbors_of_a_small_table(self):
        for method in ("HNSW", "IVF"):
            for metric in ("euclidean", "cosine", "dot"):
                for storage in ("HEAP", "SEQUENTIAL", "BTREE"):
                    with self.subTest(method=method, metric=metric, storage=storage):
                        self.create(method, metric, storage)
                        rows = self.rows("SELECT foto, SIMILARITY_SCORE() FROM imagenes "
                                         f"WHERE SIMILAR_TO('img/consulta.jpg', k=4) USING {method} "
                                         f"WITH METRIC={metric}")
                        expected = brute_force("img/consulta.jpg", self.paths(), metric)[:4]
                        self.assertEqual([row[0] for row in rows], [path for path, _ in expected])
                        for (_, score), (_, value) in zip(rows, expected):
                            self.assertAlmostEqual(score, value, places=5)
                        self.reset()


class TestExplain(MediaRowsTestCase):
    def plan(self, sql):
        return "\n".join(self.execute(sql).plan)

    def test_explain_shows_index_metric_and_k(self):
        self.create("HNSW", "cosine")
        plan = self.plan(f"EXPLAIN SELECT * FROM imagenes WHERE {self.SIMILAR.format(k=3)}")
        self.assertIn("Vector Search using imagenes_foto on imagenes", plan)
        self.assertIn("Vector Cond: similar_to(foto, 'img/consulta.jpg', k=3)", plan)
        self.assertIn("Index: HNSW (M: 8; ef_construction: 50; ef_search: 50); Metric: cosine", plan)
        self.assertIn("Score: cosine similarity", plan)
        self.assertIn("rows=3", self.execute(f"EXPLAIN SELECT * FROM imagenes WHERE {self.SIMILAR.format(k=3)}").plan[0])

    def test_explain_does_not_search(self):
        self.create("HNSW", "cosine")
        index = self.motor.catalog.table("imagenes").indexes["foto"].index
        index.reset_stats()
        self.plan(f"EXPLAIN SELECT * FROM imagenes WHERE {self.SIMILAR.format(k=3)}")
        self.assertEqual(index.stats.searches, 0)

    def test_explain_limit_reduces_k_and_rows(self):
        self.create("HNSW", "cosine")
        plan = self.execute(f"EXPLAIN SELECT * FROM imagenes WHERE {self.SIMILAR.format(k=5)} LIMIT 2").plan
        self.assertIn("k=2", "\n".join(plan))

    def test_analyze_reports_the_nodes_visited_by_hnsw(self):
        self.create("HNSW", "euclidean")
        index = self.motor.catalog.table("imagenes").indexes["foto"].index
        index.reset_stats()
        plan = self.plan(f"EXPLAIN ANALYZE SELECT id FROM imagenes WHERE {self.SIMILAR.format(k=3)}")
        self.assertIn(f"Nodes Visited: {index.stats.vectors_compared}; Neighbors Returned: 3", plan)
        self.assertGreater(index.stats.vectors_compared, 0)
        self.assertIn("Score: 1 / (1 + euclidean distance)", plan)

    def test_analyze_reports_the_vectors_compared_by_ivf(self):
        self.create("IVF", "dot")
        plan = self.plan("EXPLAIN ANALYZE SELECT id FROM imagenes "
                         "WHERE SIMILAR_TO('img/consulta.jpg', k=2) USING IVF WITH METRIC=dot")
        self.assertIn("Index: IVF (nlist: -; exact search until 16 vectors); Metric: dot", plan)
        self.assertIn("Vectors Compared: 6; Neighbors Returned: 2", plan)

    def test_explain_shows_score_in_sort_and_filter(self):
        self.create()
        plan = self.plan(f"EXPLAIN SELECT id FROM imagenes WHERE {self.SIMILAR.format(k=3)} "
                         "AND SIMILARITY_SCORE() > 0.5 ORDER BY SIMILARITY_SCORE()")
        self.assertIn("Sort Key: similarity_score()", plan)
        self.assertIn("Filter: (similarity_score() > 0.5)", plan)
        plan = self.plan(f"EXPLAIN SELECT id FROM imagenes WHERE {self.SIMILAR.format(k=3)} "
                         "ORDER BY SIMILARITY_SCORE() DESC")
        self.assertNotIn("Sort", plan)


if __name__ == "__main__":
    unittest.main()
