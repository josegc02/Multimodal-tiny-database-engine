import unittest

from frontend.sql_highlight import keyword_spans


class TestSqlHighlight(unittest.TestCase):
    def test_keywords_are_case_insensitive_and_ignore_literals_comments(self):
        sql = "select 'from select' as texto -- where delete\nFROM datos WHERE id=1"
        values = [sql[start:end] for start, end in keyword_spans(sql)]
        self.assertEqual(values, ["select", "as", "FROM", "WHERE"])

    def test_block_comments_and_identifiers_are_not_highlighted(self):
        sql = "/* SELECT FROM */ SELECTOR, _where, SELECT * FROM t"
        values = [sql[start:end] for start, end in keyword_spans(sql)]
        self.assertEqual(values, ["SELECT", "FROM"])
