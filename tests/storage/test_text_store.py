import os
import shutil
import tempfile
import unittest

from engine.storage.clustered_file import ClusteredBPlusFile, max_clustered_order
from engine.storage.heap_file import HeapFile
from engine.storage.record import Schema
from engine.storage.sequential_file import SequentialFile
from engine.storage.text_store import TextStore


class TextStoreTestCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.directory, True)
        self.path = os.path.join(self.directory, "docs.text")
        self.store = TextStore(self.path)
        self.addCleanup(self.store.close)


class TestTextStore(TextStoreTestCase):
    def test_returns_each_text_by_its_reference(self):
        references = [(text, self.store.put(text)) for text in ("hola", "", "canción ñandú", "x" * 100_000)]
        for text, reference in references:
            self.assertEqual(self.store.get(*reference), text)

    def test_the_same_text_is_stored_once(self):
        self.assertEqual(self.store.put("canción"), self.store.put("canción"))
        self.assertEqual(os.path.getsize(self.path), len("canción".encode("utf-8")))

    def test_file_is_not_created_until_the_first_text(self):
        self.assertFalse(os.path.exists(self.path))
        self.store.put("hola")
        self.assertTrue(os.path.exists(self.path))

    def test_texts_survive_reopening(self):
        reference = self.store.put("primero")
        self.store.close()
        with_reopened = TextStore(self.path)
        self.addCleanup(with_reopened.close)
        second = with_reopened.put("segundo")
        self.assertEqual(with_reopened.get(*reference), "primero")
        self.assertEqual(with_reopened.get(*second), "segundo")


class TestSchemaWithText(TextStoreTestCase):
    def schema_def(self):
        return [("id", "int"), ("contenido", "text", self.store)]

    def test_the_record_only_keeps_a_reference(self):
        schema = Schema(self.schema_def())
        self.assertEqual(schema.record_size, 8 + 12)
        record = {"id": 1, "contenido": "documento " * 2000}
        self.assertEqual(len(schema.serialize(record)), schema.record_size)
        self.assertEqual(schema.deserialize(schema.serialize(record)), record)

    def test_every_storage_keeps_documents_larger_than_a_page(self):
        documents = {number: f"documento {number} " * 1000 for number in range(1, 40)}
        storages = (
            HeapFile(os.path.join(self.directory, "t.db"), self.schema_def()),
            SequentialFile(os.path.join(self.directory, "t.main"), os.path.join(self.directory, "t.aux"),
                           self.schema_def(), key_field="id"),
            ClusteredBPlusFile(os.path.join(self.directory, "t.bpt"), self.schema_def(), key_field="id"),
        )
        for storage in storages:
            self.addCleanup(storage.close)
            with self.subTest(storage=type(storage).__name__):
                for number, text in documents.items():
                    storage.insert({"id": number, "contenido": text})
                self.assertEqual({record["id"]: record["contenido"] for _, record in storage.scan()}, documents)

    def test_moving_records_does_not_store_their_text_again(self):
        storage = ClusteredBPlusFile(os.path.join(self.directory, "t.bpt"), self.schema_def(), key_field="id",
                                     order=max_clustered_order(self.schema_def(), "id", 4096))
        self.addCleanup(storage.close)
        texts = [f"documento {number} " * 50 for number in range(2000)]
        for number, text in enumerate(texts):
            storage.insert({"id": number, "contenido": text})
        self.assertEqual(os.path.getsize(self.path), sum(len(text) for text in texts))


if __name__ == "__main__":
    unittest.main()
