import os
import random
import shutil
import tempfile
import unittest
from types import SimpleNamespace

from engine.indexes.rtree import FREE_LINK, MAX_INTERNAL, MAX_LEAF, NO_PAGE, PAGE_SIZE, RTree, _area, _rid
from engine.spatial.geometry import MBR, Point
from engine.storage.record import RID


def lima_point(rng):
    return Point(round(rng.uniform(-12.3, -11.75), 6), round(rng.uniform(-77.2, -76.8), 6))


def random_window(rng):
    lat1, lat2 = sorted(rng.uniform(-12.35, -11.7) for _ in range(2))
    lon1, lon2 = sorted(rng.uniform(-77.25, -76.75) for _ in range(2))
    return MBR(lat1, lon1, lat2, lon2)


class RTreeTestCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.path = os.path.join(self.dir, "puntos.rtree")

    def open(self, max_entries=4):
        tree = RTree(self.path, max_entries=max_entries)
        self.addCleanup(tree.close)
        return tree

    def assert_invariants(self, tree, expected):
        """Altura balanceada, ocupación m..M, MBRs exactos y ninguna página perdida."""
        leaves_seen, pages_seen = [], set()

        def visit(page_id, level, box_in_parent, is_root):
            node = tree._read_node(page_id)
            pages_seen.add(page_id)
            self.assertEqual(node.level, level)
            if is_root:
                self.assertTrue(node.is_leaf or len(node.entries) >= 2)
            else:
                self.assertGreaterEqual(len(node.entries), tree._min_entries(node))
                self.assertEqual(node.box(), box_in_parent)
            self.assertLessEqual(len(node.entries), tree._capacity(node))
            if node.is_leaf:
                leaves_seen.extend((Point(b[0], b[1]), _rid(rid)) for b, rid in node.entries)
            else:
                for box, child in node.entries:
                    visit(child, level - 1, box, False)

        visit(tree.root, tree.height - 1, None, True)
        self.assertEqual(sorted(leaves_seen, key=repr), sorted(expected, key=repr))
        self.assertEqual(len(tree), len(expected))

        free, page = set(), tree.free_head
        while page != NO_PAGE:
            free.add(page)
            tree._fh.seek(page * PAGE_SIZE)
            page = FREE_LINK.unpack(tree._fh.read(FREE_LINK.size))[0]
        self.assertFalse(free & pages_seen)
        self.assertEqual(pages_seen | free, set(range(1, tree.page_count)))

    def brute_window(self, entries, window):
        return sorted(((p, r) for p, r in entries if window.contains_point(p)), key=repr)


class TestRTreeStructure(RTreeTestCase):
    def test_default_capacity_fills_a_page(self):
        tree = self.open(max_entries=None)
        self.assertEqual((tree.max_leaf, tree.max_internal), (MAX_LEAF, MAX_INTERNAL))
        self.assertEqual((MAX_LEAF, MAX_INTERNAL), (177, 113))
        self.assertEqual(tree.stats()["height"], 1)

    def test_insert_splits_and_search_matches_brute_force(self):
        rng = random.Random(18)
        tree = self.open()
        entries = []
        for i in range(600):
            entries.append((lima_point(rng), RID(i // 50, i % 50)))
            tree.insert(*entries[-1])
            if i % 97 == 0:
                self.assert_invariants(tree, entries)
        self.assert_invariants(tree, entries)
        self.assertGreaterEqual(tree.height, 4)
        for _ in range(100):
            window = random_window(rng)
            self.assertEqual(sorted(tree.search_mbr(window), key=repr), self.brute_window(entries, window))
            self.assertLessEqual(tree.last_stats.nodes_visited, tree.stats()["nodes"])

    def test_duplicate_points_and_collinear_data(self):
        tree = self.open()
        same = Point(-12.0464, -77.0428)
        entries = [(same, RID(0, i)) for i in range(30)]
        entries += [(Point(-12.0, -77.0 + i / 1000), RID(1, i)) for i in range(60)]  # misma latitud
        entries += [(Point(-12.1 + i / 1000, -77.1), RID(2, i)) for i in range(60)]  # misma longitud
        for entry in entries:
            tree.insert(*entry)
        self.assert_invariants(tree, entries)
        self.assertEqual(sorted(tree.search(same), key=repr), sorted((r for _, r in entries[:30]), key=repr))
        self.assertEqual(len(tree.search_mbr(MBR(-12.0, -77.0, -12.0, -76.95))), 51)

    def test_delete_condenses_and_reuses_pages(self):
        rng = random.Random(7)
        tree = self.open()
        entries = [(lima_point(rng), RID(0, i)) for i in range(400)]
        for entry in entries:
            tree.insert(*entry)
        pages_full = tree.page_count
        rng.shuffle(entries)
        for i, entry in enumerate(entries[:300]):
            self.assertTrue(tree.delete(*entry))
            if i % 37 == 0:
                self.assert_invariants(tree, entries[i + 1:])
        remaining = entries[300:]
        self.assert_invariants(tree, remaining)
        self.assertFalse(tree.delete(*entries[0]))
        self.assertFalse(tree.delete(Point(0, 0), RID(9, 9)))

        for i in range(300):  # las páginas liberadas se reutilizan
            remaining.append((lima_point(rng), RID(1, i)))
            tree.insert(*remaining[-1])
        self.assert_invariants(tree, remaining)
        self.assertLessEqual(tree.page_count, pages_full + 10)

    def test_delete_everything_and_one_of_two_identical_pairs(self):
        tree = self.open()
        p, rid = Point(-12, -77), RID(0, 0)
        tree.insert(p, rid)
        tree.insert(p, rid)
        self.assertTrue(tree.delete(p, rid))
        self.assertEqual(tree.search(p), [rid])
        rng = random.Random(3)
        entries = [(p, rid)] + [(lima_point(rng), RID(0, i + 1)) for i in range(100)]
        for entry in entries[1:]:
            tree.insert(*entry)
        for entry in entries:
            self.assertTrue(tree.delete(*entry))
        self.assert_invariants(tree, [])
        self.assertEqual(tree.height, 1)

    def test_persistence(self):
        rng = random.Random(25)
        entries = [(lima_point(rng), RID(i, 0, "aux" if i % 2 else "main")) for i in range(300)]
        with RTree(self.path, max_entries=5) as tree:
            for entry in entries[:200]:
                tree.insert(*entry)
            height = tree.height
        with RTree(self.path) as tree:
            self.assertEqual((tree.height, tree.max_leaf), (height, 5))
            self.assert_invariants(tree, entries[:200])
            for entry in entries[200:]:
                tree.insert(*entry)
            for entry in entries[:50]:
                tree.delete(*entry)
        with RTree(self.path) as tree:
            self.assert_invariants(tree, entries[50:])
            self.assertEqual(sorted(tree, key=repr), sorted(entries[50:], key=repr))

    def test_bulk_load_from_storage(self):
        rows = [(RID(0, i), {"id": i, "ubicacion": (-12 - i / 100, -77)}) for i in range(20)]
        storage = SimpleNamespace(schema=SimpleNamespace(fields=["id", "ubicacion"]), scan=lambda: iter(rows))
        tree = self.open()
        tree.insert(Point(0, 0), RID(9, 9))
        self.assertEqual(tree.bulk_load_from_storage(storage, "ubicacion"), 20)
        self.assert_invariants(tree, [(Point(*row["ubicacion"]), rid) for rid, row in rows])
        with self.assertRaises(ValueError):
            tree.bulk_load_from_storage(storage, "no_existe")

    def test_quadratic_split_separates_clusters(self):
        tree = self.open(max_entries=10)
        rng = random.Random(1)
        for i in range(11):  # dos grupos lejanos: el split no debe mezclarlos
            lat = -12 if i % 2 else -5
            tree.insert(Point(lat + rng.random() / 100, -77 + rng.random() / 100), RID(0, i))
        root = tree._read_node(tree.root)
        self.assertEqual(len(root.entries), 2)
        self.assertTrue(all(_area(box) < 0.001 for box, _ in root.entries))

    def test_invalid_arguments(self):
        tree = self.open()
        with self.assertRaises(TypeError):
            tree.insert((-12, -77), RID(0, 0))
        with self.assertRaises(TypeError):
            tree.insert(Point(-12, -77), (0, 0))
        with self.assertRaises(TypeError):
            tree.insert(Point(-12, -77), RID(0, 0, "otro"))
        tree.close()
        with self.assertRaises(ValueError):
            RTree(self.path, max_entries=6)  # el archivo se creó con M = 4
        for bad in (2, 500, 4.0):
            with self.assertRaises(ValueError):
                RTree(os.path.join(self.dir, "otro.rtree"), max_entries=bad)
        not_rtree = os.path.join(self.dir, "texto.rtree")
        with open(not_rtree, "wb") as stream:
            stream.write(b"hola")
        with self.assertRaises(ValueError):
            RTree(not_rtree)


if __name__ == "__main__":
    unittest.main()
