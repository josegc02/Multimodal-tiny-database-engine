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
        return sorted(result, key=lambda row: (-row[1], row[0]))

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
