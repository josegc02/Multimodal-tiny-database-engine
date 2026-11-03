import math
import unittest

import numpy as np

from engine.vector import (cosine_similarity, cosine_similarity_batch,
                           dot_product, dot_product_batch, euclidean,
                           euclidean_batch)


class TestVectorMetrics(unittest.TestCase):
    def test_euclidean(self):
        self.assertEqual(euclidean([3, 4], [0, 0]), 5)
        self.assertEqual(euclidean([1, 2], [1, 2]), 0)
        with self.assertRaises(ValueError):
            euclidean([1], [1, 2])

    def test_dot_product(self):
        # 1*4 + 2*(-5) + 3*6 = 12.
        self.assertEqual(dot_product([1, 2, 3], [4, -5, 6]), 12)
        self.assertEqual(dot_product([1, 0], [0, 1]), 0)
        with self.assertRaises(ValueError):
            dot_product([1], [1, 2])

    def test_cosine_similarity(self):
        self.assertAlmostEqual(cosine_similarity([1, 0], [1, 1]), 1 / math.sqrt(2))
        self.assertEqual(cosine_similarity([1, 0], [-1, 0]), -1)
        with self.assertRaises(ValueError):
            cosine_similarity([0, 0], [1, 0])
        with self.assertRaises(ValueError):
            cosine_similarity([1], [1, 2])

    def test_euclidean_batch(self):
        np.testing.assert_allclose(
            euclidean_batch([[3, 4], [1, 0]], [[0, 0], [1, 1]]), [5, 1]
        )

    def test_dot_product_batch(self):
        np.testing.assert_allclose(
            dot_product_batch([[1, 2, 3], [1, 0, 0]], [[4, -5, 6], [0, 1, 0]]),
            [12, 0],
        )

    def test_cosine_similarity_batch(self):
        np.testing.assert_allclose(
            cosine_similarity_batch([[1, 0], [1, 1]], [[1, 1], [-1, 1]]),
            [1 / math.sqrt(2), 0],
        )
        with self.assertRaises(ValueError):
            cosine_similarity_batch([[1, 0], [0, 0]], [[1, 1], [1, 0]])

    def test_batch_shapes(self):
        for metric in (euclidean_batch, dot_product_batch, cosine_similarity_batch):
            with self.subTest(metric=metric.__name__):
                with self.assertRaises(ValueError):
                    metric([[1, 2]], [[1]])
                with self.assertRaises(ValueError):
                    metric([1, 2], [1, 2])


if __name__ == "__main__":
    unittest.main()
