import math
import os
import shutil
import tempfile
import unittest

from engine.indexes.spimi import SpimiIndex, tf_weight
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
