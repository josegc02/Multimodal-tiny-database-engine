import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from engine.indexes.bplus_tree import BPlusTree, EMPTY_CHILD


def check_tree(test, tree):
    leaves, depths, visited = [], set(), set()
    def visit(pos, depth, root=False):
        test.assertNotIn(pos, visited)
        visited.add(pos)
        node = tree._read_node(pos)
        test.assertEqual(node.keys, sorted(node.keys))
        test.assertEqual(node.fullness, len(node.keys))
        if not root:
            minimum = tree._min_leaf_keys() if node.isLeaf else tree._min_internal_keys()
            test.assertGreaterEqual(node.fullness, minimum)
        if node.isLeaf:
            leaves.append(pos)
            depths.add(depth)
            return node.keys[0], node.keys[-1]
        children = node.childs[:node.fullness + 1]
        bounds = [visit(child, depth + 1) for child in children]
        test.assertEqual(node.keys, [lower for lower, _ in bounds[1:]])
        for (_, previous), (following, _) in zip(bounds, bounds[1:]):
            test.assertLessEqual(previous, following)
        return bounds[0][0], bounds[-1][1]
    if tree.header.root_pos == EMPTY_CHILD:
        test.assertEqual(tree.header.min_node_pos, EMPTY_CHILD)
        return
    visit(tree.header.root_pos, 0, True)
    test.assertEqual(len(depths), 1)
    test.assertEqual(tree.header.min_node_pos, leaves[0])
    for pos, following in zip(leaves, leaves[1:] + [EMPTY_CHILD]):
        test.assertEqual(tree._read_node(pos).nextLeaf, following)


class TestBPlusTree(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / "tree.bpt")

    def tree(self, **kwargs):
        tree = BPlusTree(self.path, [("id", "int")], "id", **kwargs)
        self.addCleanup(tree.close)
        return tree

    def test_splits_search_ranges_and_reopen(self):
        tree = self.tree(M=3, page_size=128)
        for key in list(range(150))[::-1]:
            self.assertTrue(tree.insert(key, key * 3))
        check_tree(self, tree)
        self.assertFalse(tree.insert(30, 999))
        self.assertIsNone(tree.search(-1))
        for key in range(150):
            self.assertEqual(tree.search(key), key * 3)
        self.assertEqual(tree.range_search(10, 20, include_lower=False, include_upper=False),
                         [(key, key * 3) for key in range(11, 20)])
        self.assertEqual(tree.range_search(20, 10), [])
        tree.close()
        tree = self.tree()
        self.assertEqual(tree.header.M, 3)
        self.assertEqual(tree.range_search(), [(k, k * 3) for k in range(150)])
        check_tree(self, tree)

    def test_randomized_insert_delete_invariants(self):
        for order in (2, 3, 4, 5, 8):
            self.path = str(Path(self.tmp.name) / f"order{order}")
            tree = self.tree(M=order, page_size=256)
            expected = {}
            rng = random.Random(2026 + order)
            with patch.object(tree, "_reset_tree_storage", side_effect=AssertionError("No reconstruir")):
                for step in range(1200):
                    key = rng.randrange(180)
                    if rng.random() < .55:
                        self.assertEqual(tree.insert(key, key * 2), key not in expected)
                        expected.setdefault(key, key * 2)
                    else:
                        self.assertEqual(tree.delete(key), key in expected)
                        expected.pop(key, None)
                    if step % 25 == 0:
                        check_tree(self, tree)
                        self.assertEqual(tree.range_search(), sorted(expected.items()))
                keys = list(expected)
                rng.shuffle(keys)
                for key in keys:
                    self.assertTrue(tree.delete(key))
                    check_tree(self, tree)
            self.assertEqual(tree.range_search(), [])
            self.assertTrue(tree.insert(42, 1))
            self.assertEqual(tree.search(42), 1)

    def test_invalid_configuration_and_truncation(self):
        for kwargs in ({"M": 1}, {"M": True}, {"page_size": 8}, {"M": 100, "page_size": 128}):
            with self.assertRaises(ValueError):
                self.tree(**kwargs)
        Path(self.path).unlink(missing_ok=True)
        tree = self.tree()
        for key in (float("nan"), "1", 1 << 70, True):
            with self.assertRaises(ValueError):
                tree.insert(key, 1)
        tree.insert(1, 1)
        tree.close()
        with open(self.path, "r+b") as fh:
            fh.truncate(70)
        with self.assertRaises(ValueError):
            self.tree()


if __name__ == "__main__":
    unittest.main()
