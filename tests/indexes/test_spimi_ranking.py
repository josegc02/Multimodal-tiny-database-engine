import math
import os
import random
import shutil
import tempfile
import unittest
from unittest.mock import patch

from engine.indexes.spimi import DOCUMENTS_PER_PAGE, SpimiIndex, tf_weight
from engine.storage.record import RID


class TestTfIdfRanking(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.directory, True)
        self.path = os.path.join(self.directory, "docs.spimi")
        self.texts = ["gato gato negro", "gato blanco", "perro negro", "gato perro perro"]
        self.rids = [RID(index, 0) for index in range(len(self.texts))]
        self.index = SpimiIndex(self.path)
        self.addCleanup(self.index.close)
        self.index.build(zip(self.texts, self.rids))

    def brute_force(self, query):
        query_terms = self.index.analyze(query)
        query_weights = {}
        for term, tf in query_terms.items():
            df = sum(term in self.index.analyze(text) for text in self.texts)
            if df:
                weight = tf_weight(tf) * math.log10(len(self.texts) / df)
                if weight:
                    query_weights[term] = weight
        query_norm = math.sqrt(sum(weight * weight for weight in query_weights.values()))
        if not query_norm:
            return []
        result = []
        for rid, text in zip(self.rids, self.texts):
            terms = self.index.analyze(text)
            norm = math.sqrt(sum(tf_weight(tf) ** 2 for tf in terms.values()))
            dot = sum(query_weights[term] * tf_weight(terms[term])
                      for term in query_weights if term in terms)
            if norm and dot:
                result.append((rid, dot / (query_norm * norm)))
        return sorted(result, key=lambda row: (-row[1], self.rids.index(row[0])))

    def test_matches_brute_force_and_alias(self):
        expected = self.brute_force("gato negro")
        actual = self.index.rank_tfidf("gato negro", 10)
        self.assertEqual([rid for rid, _ in actual], [rid for rid, _ in expected])
        for (_, score), (_, expected_score) in zip(actual, expected):
            self.assertAlmostEqual(score, expected_score)
        self.assertEqual(self.index.cosine_search("gato negro", 2), actual[:2])

    def test_reads_only_query_postings_and_keeps_top_k(self):
        self.index.reset_stats()
        actual = self.index.rank_tfidf("gato negro", 2)
        self.assertEqual(len(actual), 2)
        # gato aparece en 3 documentos y negro en 2; no se recorren los demás.
        self.assertEqual(self.index.stats.postings_read, 5)

    def test_empty_common_terms_zero_idf_and_invalid_k(self):
        self.assertEqual(self.index.rank_tfidf("inexistente"), [])
        # perro aparece en la mitad; no es cero. Una colección de un único término sí lo es.
        with SpimiIndex(os.path.join(self.directory, "same.spimi")) as same:
            same.build([("comun", RID(0, 0)), ("comun comun", RID(1, 0))])
            self.assertEqual(same.rank_tfidf("comun"), [])
        with self.assertRaises(ValueError):
            self.index.rank_tfidf("gato", -1)


class TestRankingWithDeletes(unittest.TestCase):
    ROWS = [("gato gato perro", RID(0, 0)), ("gato", RID(1, 0)), ("gato perro", RID(2, 0)),
            ("gato raton", RID(3, 0)), ("gato ave", RID(4, 0)), ("perro loro", RID(5, 0))]
    DELETED = ROWS[3:5]

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.directory, True)
        self.index = SpimiIndex(os.path.join(self.directory, "docs.spimi"), min_changes=10 ** 9)
        self.addCleanup(self.index.close)
        self.index.build(self.ROWS)
        for text, rid in self.DELETED:
            self.index.delete(text, rid)
        self.rebuilt = SpimiIndex(os.path.join(self.directory, "rebuilt.spimi"))
        self.addCleanup(self.rebuilt.close)
        self.rebuilt.build(row for row in self.ROWS if row not in self.DELETED)

    def test_deleted_documents_do_not_change_scores(self):
        for rank in ("rank_tfidf", "rank_bm25"):
            for query in ("gato", "perro", "gato perro", "loro gato"):
                with self.subTest(rank=rank, query=query):
                    actual = getattr(self.index, rank)(query)
                    expected = getattr(self.rebuilt, rank)(query)
                    self.assertEqual([rid for rid, _ in actual], [rid for rid, _ in expected])
                    for (_, score), (_, expected_score) in zip(actual, expected):
                        self.assertAlmostEqual(score, expected_score)

    def test_scores_are_not_negative_when_df_exceeds_n(self):
        self.assertGreater(self.index.df(next(iter(self.index.analyze("gato")))), self.index.doc_count)
        for rank in ("rank_tfidf", "rank_bm25"):
            with self.subTest(rank=rank):
                self.assertGreater(len(getattr(self.index, rank)("gato perro")), 0)
                self.assertTrue(all(score > 0 for _, score in getattr(self.index, rank)("gato perro")))


class TestDocumentPagesRead(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.directory, True)
        self.index = SpimiIndex(os.path.join(self.directory, "docs.spimi"))
        self.addCleanup(self.index.close)
        self.count = 3 * DOCUMENTS_PER_PAGE
        self.index.build((f"gato perro raton{number % 2}", RID(number, 0)) for number in range(self.count))

    def document_pages(self, method):
        pages = []
        read_pages = self.index._read_pages

        def read(start, count=1):
            if start >= self.index.documents_start:
                pages.append(start)
            return read_pages(start, count)

        with patch.object(self.index, "_read_pages", read):
            self.assertTrue(method("gato raton0"))
        return pages

    def test_each_page_of_the_document_table_is_read_once(self):
        start = self.index.documents_start
        for method in (self.index.rank_tfidf, self.index.rank_bm25, self.index.search):
            with self.subTest(method=method.__name__):
                self.assertEqual(self.document_pages(method), [start, start + 1, start + 2])

    def test_documents_includes_those_in_the_delta(self):
        self.index.insert("gato raton0 nuevo", RID(self.count, 0))
        documents = self.index._documents([0, self.count])
        self.assertEqual(documents[0].rid, RID(0, 0))
        self.assertEqual(documents[self.count].rid, RID(self.count, 0))
        self.assertEqual(documents[self.count].length, self.index.document(self.count).length)


class TestBm25Ranking(TestTfIdfRanking):
    def brute_force(self, query, k1=1.2, b=0.75):
        query_terms = self.index.analyze(query)
        average_length = sum(sum(self.index.analyze(text).values()) for text in self.texts) / len(self.texts)
        result = []
        for number, (rid, text) in enumerate(zip(self.rids, self.texts)):
            terms = self.index.analyze(text)
            length = sum(terms.values())
            score = 0.0
            for term in query_terms:
                if term not in terms:
                    continue
                df = sum(term in self.index.analyze(candidate) for candidate in self.texts)
                idf = math.log1p((len(self.texts) - df + 0.5) / (df + 0.5))
                normalization = k1 * (1 - b + b * length / average_length)
                score += idf * terms[term] * (k1 + 1) / (terms[term] + normalization)
            if score:
                result.append((number, rid, score))
        return [(rid, score) for _, rid, score in sorted(result, key=lambda row: (-row[2], row[0]))]

    def test_matches_brute_force_and_alias(self):
        expected = self.brute_force("gato negro")
        actual = self.index.rank_bm25("gato negro")
        self.assertEqual([rid for rid, _ in actual], [rid for rid, _ in expected])
        for (_, score), (_, expected_score) in zip(actual, expected):
            self.assertAlmostEqual(score, expected_score)
        self.assertEqual(self.index.bm25_search("gato negro", 2), actual[:2])

    def test_parameters_top_k_and_postings(self):
        self.index.reset_stats()
        self.assertEqual(len(self.index.rank_bm25("gato negro", 2, k1=2, b=0)), 2)
        self.assertEqual(self.index.stats.postings_read, 5)
        for parameters in (
            {"top_k": -1}, {"k1": 0}, {"k1": float("nan")},
            {"b": -0.1}, {"b": 1.1},
        ):
            with self.subTest(parameters=parameters), self.assertRaises(ValueError):
                self.index.rank_bm25("gato", **parameters)


class TestRankingAgainstBruteForce(unittest.TestCase):
    VOCABULARY = [f"termino{number}x" for number in range(60)]

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.directory, True)
        self.random = random.Random(46)
        self.index = SpimiIndex(os.path.join(self.directory, "docs.spimi"), block_size=4096,
                                min_changes=10 ** 9)
        self.addCleanup(self.index.close)
        self.texts = {RID(number, 0): self.text(1, 30) for number in range(300)}
        self.index.build((text, rid) for rid, text in self.texts.items())

    def text(self, minimum, maximum):
        return " ".join(self.random.choices(self.VOCABULARY, k=self.random.randint(minimum, maximum)))

    def expected(self, query):
        documents = {rid: self.index.analyze(text) for rid, text in self.texts.items()}
        terms = self.index.analyze(query)
        count = len(documents)
        average_length = sum(sum(document.values()) for document in documents.values()) / count
        df = {term: sum(term in document for document in documents.values()) for term in terms}
        weights = {term: tf_weight(tf) * math.log10(count / df[term]) for term, tf in terms.items() if df[term]}
        query_norm = math.sqrt(sum(weight * weight for weight in weights.values()))
        tfidf, bm25 = {}, {}
        for rid, document in documents.items():
            common = [term for term in terms if term in document]
            if not common:
                continue
            length = sum(document.values())
            norm = math.sqrt(sum(tf_weight(tf) ** 2 for tf in document.values()))
            bm25[rid] = sum(math.log1p((count - df[term] + 0.5) / (df[term] + 0.5)) * document[term] * 2.2
                            / (document[term] + 1.2 * (0.25 + 0.75 * length / average_length)) for term in common)
            dot = sum(weights[term] * tf_weight(document[term]) for term in common)
            if query_norm and dot:
                tfidf[rid] = dot / (query_norm * norm)
        return tfidf, bm25

    def assert_ranking(self, actual, expected, top_k):
        self.assertEqual(len(actual), min(top_k, len(expected)))
        best = sorted(expected.values(), reverse=True)[:top_k]
        for (rid, score), best_score in zip(actual, best):
            self.assertAlmostEqual(score, expected[rid])
            self.assertAlmostEqual(score, best_score)

    def assert_matches(self, queries=30):
        for _ in range(queries):
            query = self.text(1, 5)
            tfidf, bm25 = self.expected(query)
            for top_k in (1, 5, 1000):
                with self.subTest(query=query, top_k=top_k):
                    self.assert_ranking(self.index.rank_tfidf(query, top_k), tfidf, top_k)
                    self.assert_ranking(self.index.rank_bm25(query, top_k), bm25, top_k)

    def apply_changes(self):
        next_number = len(self.texts)
        for _ in range(150):
            if self.random.random() < 0.4:
                rid = self.random.choice(list(self.texts))
                self.index.delete(self.texts.pop(rid), rid)
            else:
                rid, next_number = RID(next_number, 0), next_number + 1
                self.texts[rid] = self.text(1, 30)
                self.index.insert(self.texts[rid], rid)

    def test_matches_after_build(self):
        self.assert_matches()

    def test_matches_with_pending_changes_and_after_consolidating(self):
        self.apply_changes()
        self.assert_matches()
        self.index.consolidate()
        self.assert_matches()

    def test_ties_keep_the_smallest_doc_id(self):
        rows = [("gato", RID(number, 0)) for number in range(6)] + [("perro", RID(6, 0))]
        with SpimiIndex(os.path.join(self.directory, "ties.spimi")) as index:
            index.build(rows)
            for rank in (index.rank_tfidf, index.rank_bm25):
                with self.subTest(rank=rank.__name__):
                    self.assertEqual([rid for rid, _ in rank("gato", 3)], [RID(number, 0) for number in range(3)])
