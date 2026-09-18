import unittest

from engine.query import Lexer, SQLLexError, tokenize


class TestLexer(unittest.TestCase):
    def test_keywords_identifiers_and_all_operators(self):
        tokens = tokenize('SeLeCt Product_ID <= 4, a >= 2, a != 3, a <> 5, a = 1, a < 2, a > 0 FROM T;')
        self.assertEqual(tokens[0].kind, "SELECT")
        self.assertEqual(tokens[1].value, "product_id")
        self.assertEqual(tokens[1].lexeme, "Product_ID")
        self.assertEqual([t.kind for t in tokens if t.kind in {"<=", ">=", "!=", "<>", "=", "<", ">"}],
                         ["<=", ">=", "!=", "<>", "=", "<", ">"])
        self.assertEqual(tokens[-1].kind, "EOF")

    def test_strings_quoted_identifiers_and_sql_escapes(self):
        tokens = tokenize("'O''Brien' 'café😀' '' \"Mi Tabla\" \"a\"\"b\" '\\n'")
        self.assertEqual([t.value for t in tokens[:-1]], ["O'Brien", "café😀", "", "Mi Tabla", 'a"b', '\\n'])
        self.assertEqual(tokens[3].kind, "IDENTIFIER")
        self.assertEqual(tokenize('"SELECT"')[0].kind, "IDENTIFIER")

    def test_numeric_forms_keep_sign_as_operator(self):
        tokens = tokenize('0 12 1.5 .25 2. 1e3 2.5E-2 -42 +7')
        self.assertEqual([t.value for t in tokens[:-1]], [0, 12, 1.5, .25, 2., 1000., .025, '-', 42, '+', 7])
        self.assertEqual(tokens[0].kind, "INTEGER")
        self.assertEqual(tokens[5].kind, "FLOAT")

    def test_comments_and_multiline_positions(self):
        sql = '-- first\n/* outer /* nested */ end */\nSELECT\n  id FROM t'
        tokens = tokenize(sql)
        self.assertEqual((tokens[0].line, tokens[0].column), (3, 1))
        self.assertEqual((tokens[1].line, tokens[1].column), (4, 3))
        self.assertEqual(sql[tokens[1].offset:tokens[1].offset + len(tokens[1].lexeme)], "id")
        self.assertEqual([t.kind for t in tokenize('-- EOF comment')], ['EOF'])

    def test_comment_markers_and_semicolons_inside_strings_are_data(self):
        self.assertEqual(tokenize("'-- ; /* hi */'")[0].value, '-- ; /* hi */')

    def test_lexical_errors_include_location(self):
        for sql, line, column in [("SELECT\n  @ FROM t", 2, 3), ("'unterminated", 1, 1),
                                  ('/* never closed', 1, 1), ('"unterminated', 1, 1), ('""', 1, 1)]:
            with self.subTest(sql=sql), self.assertRaises(SQLLexError) as caught:
                tokenize(sql)
            self.assertEqual((caught.exception.line, caught.exception.column), (line, column))
            self.assertIn('^', str(caught.exception))

    def test_rejects_malformed_or_infinite_numbers(self):
        for sql in ['1e', '1e+', '1.2.3', '12abc', '1e999', '123_456']:
            with self.subTest(sql=sql), self.assertRaises(SQLLexError):
                tokenize(sql)

    def test_empty_input_reuse_and_invalid_input_type(self):
        self.assertEqual(len(tokenize(' \t\r\n')), 1)
        lexer = Lexer('SELECT id FROM t')
        self.assertEqual(lexer.tokenize(), lexer.tokenize())
        with self.assertRaises(TypeError):
            tokenize(None)


if __name__ == '__main__':
    unittest.main()
