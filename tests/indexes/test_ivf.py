import tempfile
import unittest
from pathlib import Path

import numpy as np

from engine.indexes.ivf import IVFIndex


class TestIVFIndex(unittest.TestCase):
    def test_train_and_search(self):
        index = IVFIndex(2, seed=0)
        index.train({0: [0, 0], 1: [1, 0], 2: [10, 0], 3: [11, 0]})
        result = index.search([0, 0], k=2, nprobe=1)
        self.assertEqual(result.matches, [(0, 0.0), (1, 1.0)])
        self.assertEqual(result.vectors_compared, 2)
        self.assertEqual(sum(map(len, index.lists)), 4)

    def test_metric_ordering(self):
        vectors = {0: [1, 0], 1: [2, 0], 2: [-1, 0], 3: [0, 1]}
        dot = IVFIndex(2, metric="dot_product")
        dot.train(vectors)
        self.assertEqual(dot.search([1, 0], k=4, nprobe=2).matches,
                         [(1, 2.0), (0, 1.0), (3, 0.0), (2, -1.0)])

        cosine = IVFIndex(2, metric="cosine")
        cosine.train(vectors)
        self.assertEqual(cosine.search([1, 0], k=4, nprobe=2).matches,
                         [(0, 1.0), (1, 1.0), (3, 0.0), (2, -1.0)])
        with self.assertRaises(ValueError):
            cosine.insert(4, [0, 0])
        with self.assertRaises(ValueError):
            cosine.search([0, 0])

    def test_insert_delete_and_persistence(self):
        index = IVFIndex(2)
        index.train({0: [0, 0], 1: [10, 0]})
        index.insert(2, [1, 0])
        self.assertEqual(index.search([1, 0], k=1, nprobe=2).matches, [(2, 0.0)])
        with self.assertRaises(ValueError):
            index.insert(2, [2, 0])
        self.assertFalse(index.delete(99))
        self.assertTrue(index.delete(2))
        self.assertNotIn(2, [identifier for items in index.lists for identifier in items])

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.json"
            index.save(path)
            restored = IVFIndex.load(path)
            self.assertEqual(restored.search([0, 0], k=2, nprobe=2),
                             index.search([0, 0], k=2, nprobe=2))
            restored.insert(3, [2, 0])
            self.assertEqual(restored.search([2, 0], k=1, nprobe=2).matches, [(3, 0.0)])

    def test_invalid_inputs(self):
        with self.assertRaises(ValueError):
            IVFIndex(0)
        with self.assertRaises(ValueError):
            IVFIndex(1, metric="unknown")
        index = IVFIndex(2)
        with self.assertRaises(ValueError):
            index.search([1, 2])
        with self.assertRaises(ValueError):
            index.train({0: [1, 2]})
        index.train({0: [0, 0], 1: [1, 1]})
        with self.assertRaises(ValueError):
            index.search([0, 0], nprobe=3)
        with self.assertRaises(ValueError):
            index.insert(2, [1])

    def test_recall_at_10_against_exact_search(self):
        rng = np.random.default_rng(55)
        data = rng.normal(size=(200, 4))
        vectors = {i: vector for i, vector in enumerate(data)}
        queries = rng.normal(size=(5, 4))

        for metric in ("euclidean", "dot_product", "cosine"):
            with self.subTest(metric=metric):
                index = IVFIndex(10, metric=metric, seed=55)
                index.train(vectors)
                for query in queries:
                    if metric == "euclidean":
                        scores = np.linalg.norm(data - query, axis=1)
                        exact = np.argsort(scores)[:10]
                    elif metric == "dot_product":
                        scores = data @ query
                        exact = np.argsort(-scores)[:10]
                    else:
                        scores = (data @ query) / (np.linalg.norm(data, axis=1) * np.linalg.norm(query))
                        exact = np.argsort(-scores)[:10]

                    result = index.search(query, k=10, nprobe=index.nlist)
                    found = {identifier for identifier, _ in result.matches}
                    recall_at_10 = len(found & set(exact)) / 10
                    self.assertEqual(recall_at_10, 1.0)
                    self.assertEqual(result.vectors_compared, len(data))

    def test_nprobe_reduces_comparisons(self):
        vectors = {i: [float(i), 0] for i in range(20)}
        vectors.update({i + 20: [100 + float(i), 0] for i in range(20)})
        index = IVFIndex(2)
        index.train(vectors)
        approximate = index.search([0, 0], k=10, nprobe=1)
        exact = index.search([0, 0], k=10, nprobe=2)
        recall_at_10 = len({i for i, _ in approximate.matches} &
                           {i for i, _ in exact.matches}) / 10
        self.assertEqual(recall_at_10, 1.0)
        self.assertLess(approximate.vectors_compared, exact.vectors_compared)


if __name__ == "__main__":
    unittest.main()
