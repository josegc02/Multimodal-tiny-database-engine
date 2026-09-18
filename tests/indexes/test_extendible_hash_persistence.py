import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from engine.indexes import ExtendibleHash
from engine.storage.record import RID


class TestExtendibleHashPersistence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "indexes" / "data.hash"

    def test_reopen_restores_configuration_keys_and_full_rids(self):
        with ExtendibleHash(2, max_depth=5, filepath=self.path) as index:
            index.bulk_load((i, RID(i, 0)) for i in range(50))
            index.bulk_load(("café", RID(0, i, "aux")) for i in range(10))
            index.insert(1.25, RID(3, 8))
            index.delete(25)
        with ExtendibleHash(filepath=self.path) as reopened:
            self.assertEqual(reopened.bucket_capacity, 2)
            self.assertEqual(reopened.max_depth, 5)
            self.assertEqual(len(reopened), 60)
            self.assertEqual(reopened.search(25), [])
            self.assertEqual(reopened.search(1.25), [RID(3, 8)])
            for i in range(50):
                if i != 25:
                    self.assertEqual(reopened.search(i), [RID(i, 0)])
            self.assertCountEqual(reopened.search("café"), [RID(0, i, "aux") for i in range(10)])
            reopened.clear()
        self.assertEqual(len(ExtendibleHash(filepath=self.path)), 0)

    def test_bulk_replacement_keeps_persistence_destination(self):
        index = ExtendibleHash(filepath=self.path)
        index.insert(1, RID(0, 0))
        index.flush()
        index.bulk_load([(2, RID(0, 1))], replace=True)
        index.close()
        loaded = ExtendibleHash(filepath=self.path)
        self.assertEqual(loaded.search(1), [])
        self.assertEqual(loaded.search(2), [RID(0, 1)])

    def test_failed_save_preserves_previous_snapshot_and_cleans_temp(self):
        index = ExtendibleHash(filepath=self.path)
        index.insert(1, RID(0, 0))
        index.flush()
        previous = self.path.read_bytes()
        index.insert(2, RID(0, 1))
        with patch("engine.indexes.extendible_hash.os.replace", side_effect=OSError("disk error")):
            with self.assertRaises(OSError):
                index.flush()
        self.assertEqual(self.path.read_bytes(), previous)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])
        self.assertEqual(ExtendibleHash(filepath=self.path).search(2), [])

    def test_rejects_corrupt_or_unsupported_snapshots(self):
        self.path.parent.mkdir()
        valid = {"format": "extendible-hash", "version": 1,
                 "bucket_capacity": 2, "max_depth": 4, "entries": []}
        invalid = [
            "not json", json.dumps([]), json.dumps({}),
            json.dumps(dict(valid, version=2)),
            json.dumps(dict(valid, bucket_capacity=0)),
            json.dumps(dict(valid, entries=[[1, -1, 0, "main"]])),
            json.dumps(dict(valid, entries=[[None, 0, 0, "main"]])),
            json.dumps(dict(valid, entries=[[1, 0]])),
        ]
        for contents in invalid:
            with self.subTest(contents=contents):
                self.path.write_text(contents)
                with self.assertRaises(ValueError):
                    ExtendibleHash(filepath=self.path)
                self.assertEqual(self.path.read_text(), contents)

    def test_stable_hash_and_reopen_across_python_processes(self):
        with ExtendibleHash(filepath=self.path) as index:
            index.insert("café", RID(5, 2, "aux"))
        code = (
            "import sys; from engine.indexes import ExtendibleHash; "
            "index = ExtendibleHash(filepath=sys.argv[1]); "
            "print(index._hash_key('café')); print(index.search('café'))"
        )
        outputs = []
        for seed in ["1", "2"]:
            outputs.append(subprocess.check_output(
                [sys.executable, "-c", code, str(self.path)],
                env=dict(os.environ, PYTHONHASHSEED=seed), text=True,
            ))
        self.assertEqual(outputs[0], outputs[1])
        self.assertIn("page_id=5, slot_id=2, file='aux'", outputs[0])

    def test_memory_only_context(self):
        with ExtendibleHash() as index:
            index.insert(1, RID(0, 0))
            index.flush()
        self.assertEqual(index.search(1), [RID(0, 0)])
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
