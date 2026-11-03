import tempfile
import unittest
from pathlib import Path

import numpy as np

from engine.indexes.hnsw import HNSWIndex


class TestHNSWIndex(unittest.TestCase):
    def test_layers_and_links(self):
        rng = np.random.default_rng(56)
        vectors = rng.normal(size=(40, 3))
        index = HNSWIndex(M=6, ef_construction=20, seed=56)
        copy = HNSWIndex(M=6, ef_construction=20, seed=56)
        for identifier, vector in enumerate(vectors):
            index.insert(identifier, vector)
            copy.insert(identifier, vector)
        self.assertEqual(index.levels, copy.levels)
        self.assertEqual(index.max_level, max(index.levels.values()))
        for identifier, layers in index.links.items():
            self.assertEqual(len(layers), index.levels[identifier] + 1)
            for layer, neighbors in enumerate(layers):
                self.assertLessEqual(len(neighbors), index.M)
                for neighbor in neighbors:
                    self.assertIn(identifier, index.links[neighbor][layer])

    def test_search_and_metric_order(self):
        vectors = {0: [1, 0], 1: [2, 0], 2: [0, 1], 3: [-1, 0]}
        for metric, expected in (
            ("euclidean", 0),
            ("dot_product", 1),
            ("cosine", 0),
        ):
            with self.subTest(metric=metric):
                index = HNSWIndex(M=4, ef_construction=8, metric=metric)
                for identifier, vector in vectors.items():
                    index.insert(identifier, vector)
                result = index.search([1, 0], k=4, ef_search=4)
                self.assertEqual(result.matches[0][0], expected)
                self.assertEqual(result.nodes_visited, 4)

    def test_save_load_and_continue_inserting(self):
        index = HNSWIndex(M=4, ef_construction=10, seed=56)
        for identifier in range(15):
            index.insert(identifier, [float(identifier), 1])
        before = index.search([6.2, 1], k=5, ef_search=10)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "graph.json"
            index.save(path)
            loaded = HNSWIndex.load(path)
            self.assertEqual(loaded.search([6.2, 1], k=5, ef_search=10), before)
            index.insert(15, [15, 1])
            loaded.insert(15, [15, 1])
            self.assertEqual(loaded.levels[15], index.levels[15])
            self.assertEqual(loaded.search([15, 1], k=1).matches, [(15, 0.0)])

    def test_invalid_inputs_and_empty_index(self):
        with self.assertRaises(ValueError):
            HNSWIndex(M=1)
        with self.assertRaises(ValueError):
            HNSWIndex(M=4, ef_construction=3)
        with self.assertRaises(ValueError):
            HNSWIndex(metric="unknown")
        index = HNSWIndex()
        self.assertEqual(index.search([1, 2]).matches, [])
        index.insert(0, [1, 2])
        with self.assertRaises(ValueError):
            index.insert(0, [2, 3])
        with self.assertRaises(ValueError):
            index.insert(1, [1])
        with self.assertRaises(ValueError):
            index.search([1, 2], k=2, ef_search=1)
        cosine = HNSWIndex(metric="cosine")
        with self.assertRaises(ValueError):
            cosine.insert(0, [0, 0])

    def test_recall_at_10_against_exact_search(self):
        rng = np.random.default_rng(56)
        data = rng.normal(size=(160, 4))
        queries = rng.normal(size=(8, 4))
        for metric in ("euclidean", "dot_product", "cosine"):
            with self.subTest(metric=metric):
                index = HNSWIndex(M=12, ef_construction=60, metric=metric, seed=56)
                for identifier, vector in enumerate(data):
                    index.insert(identifier, vector)
                recalls = []
                for query in queries:
                    if metric == "euclidean":
                        scores = np.linalg.norm(data - query, axis=1)
                        exact = np.argsort(scores)[:10]
                    elif metric == "dot_product":
                        exact = np.argsort(-(data @ query))[:10]
                    else:
                        scores = (data @ query) / (np.linalg.norm(data, axis=1) * np.linalg.norm(query))
                        exact = np.argsort(-scores)[:10]
                    result = index.search(query, k=10, ef_search=60)
                    found = {identifier for identifier, _ in result.matches}
                    recalls.append(len(found & set(exact)) / 10)
                    self.assertLessEqual(result.nodes_visited, len(data))
                self.assertGreaterEqual(sum(recalls) / len(recalls), 0.8)


if __name__ == "__main__":
    unittest.main()
