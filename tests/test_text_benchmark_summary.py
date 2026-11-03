import csv
import tempfile
import unittest
from pathlib import Path

from benchmarks.text_output import summarize, write_csv
from benchmarks.text_summary import export_summaries


class TestTextSummary(unittest.TestCase):
    def test_mean_std_and_na_are_not_confused_with_zero(self):
        rows = [{"t": "A", "time": 1, "memory": None}, {"t": "A", "time": 3, "memory": None}]
        result = summarize(rows, ("t",), ("time", "memory"))[0]
        self.assertEqual(result["time"], 2)
        self.assertAlmostEqual(result["time_std"], 2 ** 0.5)
        self.assertIsNone(result["memory"])
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "results.csv"
            write_csv(path, [result])
            with path.open() as stream:
                self.assertEqual(next(csv.DictReader(stream))["memory"], "NA")

    def test_repetition_means_have_their_own_variability(self):
        rows = [{"rep": rep, "query": q, "value": value}
                for rep, values in ((1, (0, 10)), (2, (2, 12)))
                for q, value in enumerate(values)]
        groups = summarize(rows, ("rep",), ("value",))
        result = summarize(groups, (), ("value",))[0]
        self.assertEqual(result["value"], 6)
        self.assertAlmostEqual(result["value_std"], 2 ** 0.5)
