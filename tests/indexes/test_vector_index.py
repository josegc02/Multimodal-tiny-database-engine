import os
import tempfile
import unittest

import numpy as np

from engine.indexes.vector_index import MIN_TRAIN, VectorIndex, similarity
from engine.storage.heap_file import HeapFile
from engine.storage.media_store import MediaStore


class VectorIndexTestCase(unittest.TestCase):
    DIMENSION = 8

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = temp.name
        rng = np.random.default_rng(7)
        self.vectors = {f"f{i}.jpg": rng.normal(size=self.DIMENSION) for i in range(200)}
        self.store = MediaStore(os.path.join(self.dir, "t.media"),
                                lambda kind, path: self.vectors[path])
        self.heap = HeapFile(os.path.join(self.dir, "t.db"), [("id", "int"), ("foto", "image", self.store)])
        self.addCleanup(self.store.close)
        self.addCleanup(self.heap.close)
        self.rids = {}

    def insert(self, count, start=0):
        for i in range(start, start + count):
            self.rids[i] = self.heap.insert({"id": i, "foto": f"f{i}.jpg"})

    def index(self, method, metric="euclidean"):
        index = VectorIndex(os.path.join(self.dir, f"t.{method}"), method, metric)
        index.bulk_load_from_storage(self.heap, "foto")
        return index

    def exact(self, query, metric, k, ids):
        def score(i):
            vector = self.vectors[f"f{i}.jpg"]
            if metric == "euclidean":
                return similarity(metric, float(np.linalg.norm(vector - query)))
            product = float(vector @ query)
            return product / (np.linalg.norm(vector) * np.linalg.norm(query)) if metric == "cosine" else product
        return sorted(ids, key=lambda i: -score(i))[:k]

    def ids(self, result):
        by_rid = {rid: i for i, rid in self.rids.items()}
        return [by_rid[rid] for rid, _ in result.matches]


class TestVectorIndex(VectorIndexTestCase):
    def test_finds_the_exact_neighbors_of_a_small_table(self):
        self.insert(MIN_TRAIN - 1)
        for method in ("hnsw", "ivf"):
            for metric in ("euclidean", "cosine", "dot"):
                with self.subTest(method=method, metric=metric):
                    query = self.vectors["f3.jpg"]
                    result = self.index(method, metric).knn(query, 5)
                    self.assertEqual(self.ids(result), self.exact(query, metric, 5, self.rids))
                    scores = [score for _, score in result.matches]
                    self.assertEqual(scores, sorted(scores, reverse=True))

    def test_recall_against_brute_force(self):
        self.insert(200)
        for method in ("hnsw", "ivf"):
            with self.subTest(method=method):
                index = self.index(method, "cosine")
                hits = 0
                for i in range(0, 200, 10):
                    query = self.vectors[f"f{i}.jpg"]
                    hits += len(set(self.ids(index.knn(query, 10))) & set(self.exact(query, "cosine", 10, self.rids)))
                self.assertGreaterEqual(hits / 200, 0.6)

    def test_euclidean_score_grows_with_similarity(self):
        self.insert(3)
        result = self.index("hnsw").knn(self.vectors["f0.jpg"], 3)
        self.assertEqual(result.matches[0][0], self.rids[0])
        self.assertAlmostEqual(result.matches[0][1], 1.0, places=6)
        self.assertTrue(all(0 < score <= 1 for _, score in result.matches))

    def test_inserts_and_deletes_follow_the_table(self):
        self.insert(40)
        for method in ("hnsw", "ivf"):
            with self.subTest(method=method):
                index = self.index(method)
                query = self.vectors["f5.jpg"]
                index.delete("f5.jpg", self.rids[5])
                self.assertNotIn(5, self.ids(index.knn(query, 40)))
                self.assertEqual(len(index.knn(query, 100).matches), 39)
                index.insert("f5.jpg", self.rids[5])
                self.assertEqual(self.ids(index.knn(query, 1)), [5])
                self.assertFalse(index.delete("f5.jpg", "rid inexistente"))

    def test_hnsw_rebuilds_when_most_nodes_are_deleted(self):
        self.insert(30)
        index = self.index("hnsw")
        for i in range(20):
            index.delete(f"f{i}.jpg", self.rids[i])
        # Al pasar de 15 marcas sobre 30 nodos se reconstruyó con los vivos.
        self.assertLess(len(index._hnsw.vectors), 30)
        self.assertEqual(sorted(self.ids(index.knn(self.vectors["f0.jpg"], 30))), list(range(20, 30)))

    def test_ivf_trains_and_retrains_as_the_table_grows(self):
        index = self.index("ivf")
        self.assertIsNone(index.nlist)
        self.insert(MIN_TRAIN)
        for i in range(MIN_TRAIN):
            index.insert(f"f{i}.jpg", self.rids[i])
        self.assertEqual(index.nlist, 4)
        self.insert(2 * MIN_TRAIN, start=MIN_TRAIN)
        for i in range(MIN_TRAIN, 3 * MIN_TRAIN):
            index.insert(f"f{i}.jpg", self.rids[i])
        self.assertEqual((index.nlist, index.nprobe), (6, 2))
        self.assertEqual(index.size, 3 * MIN_TRAIN)

    def test_search_returns_the_rows_with_that_path(self):
        self.insert(3)
        rid = self.heap.insert({"id": 99, "foto": "f1.jpg"})
        index = self.index("ivf")
        self.assertEqual(set(index.search("f1.jpg")), {self.rids[1], rid})
        self.assertEqual(index.search("otra.jpg"), [])

    def test_cosine_skips_null_vectors(self):
        self.vectors["cero.jpg"] = np.zeros(self.DIMENSION)
        self.insert(3)
        rid = self.heap.insert({"id": 50, "foto": "cero.jpg"})
        index = self.index("hnsw", "cosine")
        self.assertEqual(index.size, 3)
        index.insert("cero.jpg", rid)
        self.assertEqual(index.size, 3)
        with self.assertRaises(ValueError):
            index.knn(np.zeros(self.DIMENSION), 1)

    def test_rejects_invalid_queries_and_parameters(self):
        self.insert(3)
        index = self.index("hnsw")
        for query, k in ((np.ones(3), 1), (self.vectors["f0.jpg"], 0)):
            with self.subTest(k=k), self.assertRaises(ValueError):
                index.knn(query, k)
        for method, metric in (("lsh", "cosine"), ("hnsw", "manhattan")):
            with self.subTest(method=method, metric=metric), self.assertRaises(ValueError):
                VectorIndex("x", method, metric)

    def test_counts_compared_vectors(self):
        self.insert(MIN_TRAIN - 1)
        index = self.index("ivf")
        index.knn(self.vectors["f0.jpg"], 3)
        index.knn(self.vectors["f1.jpg"], 3)
        self.assertEqual((index.stats.searches, index.stats.vectors_compared), (2, 2 * (MIN_TRAIN - 1)))

    def test_close_saves_the_structure(self):
        self.insert(MIN_TRAIN)
        for method in ("hnsw", "ivf"):
            with self.subTest(method=method):
                index = self.index(method)
                index.close()
                self.assertGreater(os.path.getsize(index.filepath), 0)

    def test_empty_table(self):
        for method in ("hnsw", "ivf"):
            with self.subTest(method=method):
                index = self.index(method)
                self.assertEqual(index.knn(np.ones(self.DIMENSION), 3).matches, [])
                index.close()


if __name__ == "__main__":
    unittest.main()
