"""Adaptador de SPIMI con carga y construcción separadas."""

from contextlib import ExitStack
from pathlib import Path

from benchmarks.load_text_dataset import schema
from benchmarks.text_disk import engine_disk
from benchmarks.text_validation import read_documents
from engine.indexes.spimi import SpimiIndex
from engine.storage.heap_file import HeapFile
from engine.storage.text_store import TextStore


class EngineRun:
    def __init__(self, directory, technique):
        self.directory = Path(directory)
        self.technique = technique
        self.resources = ExitStack()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return self.resources.__exit__(*exc)

    def load(self, csv):
        texts = TextStore(str(self.directory / "news.text"))
        self.resources.callback(texts.close)
        self.storage = HeapFile(str(self.directory / "news.db"), schema(texts))
        self.resources.callback(self.storage.close)
        for row in read_documents(csv):
            self.storage.insert(row)

    def build(self):
        self.index = SpimiIndex(str(self.directory / "news.spimi"), "es")
        self.resources.callback(self.index.close)
        self.index.build((row["contenido"], rid) for rid, row in self.storage.scan())

    def disk(self):
        return engine_disk(self.directory)

    def search(self, query):
        self.index.reset_stats()
        rank = self.index.rank_tfidf if self.technique == "TF-IDF" else self.index.rank_bm25
        rows = rank(query, 10)
        return [(self.storage.get(rid)["id"], score) for rid, score in rows]

    def counters(self):
        return {"postings_read": self.index.stats.postings_read,
                "pages_read": self.index.stats.pages_read}
