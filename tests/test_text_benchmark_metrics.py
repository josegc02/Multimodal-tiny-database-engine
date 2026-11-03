import unittest

from benchmarks.text_metrics import relevance_at_k, validate_ranking
from benchmarks.text_memory import parse_status


class TestTextMetrics(unittest.TestCase):
    def test_known_precision_and_recall(self):
        result = relevance_at_k([1, 2, 9], {1, 2, 3, 4})
        self.assertEqual(result["precision"], 0.2)
        self.assertEqual(result["recall"], 0.5)
        self.assertEqual(result["hits"], 2)
        self.assertIsNone(relevance_at_k([], set())["recall"])
        self.assertEqual(relevance_at_k([], {1})["recall"], 0)

    def test_bad_rankings_are_not_silently_scored(self):
        with self.assertRaises(ValueError):
            relevance_at_k([1, 1], {1})
        for rows in ([(0, 1.0)], [(1, float("nan"))], [(1, -1.0)],
                     [(2, 1.0), (1, 1.0)], [(1, 0.5), (2, 1.0)]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                validate_ranking(rows, 10)
        validate_ranking([(1, 1.0), (2, 1.0)], 10)

    def test_proc_units_and_missing_memory(self):
        self.assertEqual(parse_status("Name: python\nVmRSS: 12 kB\nVmHWM: 24 kB\n"),
                         {"VmRSS": 12288, "VmHWM": 24576})
        with self.assertRaises(ValueError):
            parse_status("Name: postgres")
