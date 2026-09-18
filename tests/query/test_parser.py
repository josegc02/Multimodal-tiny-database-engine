from dataclasses import FrozenInstanceError
import json
import unittest

from engine.query import Parser, SQLLexError, SQLParseError, parse, parse_script
from engine.query.ast import (
    AggregateCall, Between, BinaryOp, ColumnRef, DeleteStatement, InList,
    InsertStatement, IsNull, Literal, SelectItem, SelectStatement, Star,
    TableRef, TransactionStatement, UnaryOp,
)


class TestSelectParser(unittest.TestCase):
    def test_basic_select_and_qualified_wildcard(self):
        query = parse('SELECT *, p.*, p.id AS codigo, name nombre FROM products AS p;')
        self.assertIsInstance(query, SelectStatement)
        self.assertEqual(query.from_table, TableRef('products', 'p'))
        self.assertEqual(query.columns, (
            SelectItem(Star()), SelectItem(Star('p')), SelectItem(ColumnRef('id', 'p'), 'codigo'),
            SelectItem(ColumnRef('name'), 'nombre'),
        ))

    def test_inner_joins_and_compound_on_condition(self):
        query = parse('''SELECT p.id, c.name FROM products p
                        JOIN categories c ON p.category = c.id AND c.active = TRUE
                        INNER JOIN stores s ON p.store = s.id''')
        self.assertEqual(len(query.joins), 2)
        self.assertEqual(query.joins[0].table, TableRef('categories', 'c'))
        self.assertEqual(query.joins[0].condition.operator, 'AND')
        self.assertEqual(query.joins[1].condition, BinaryOp('=', ColumnRef('store', 'p'), ColumnRef('id', 's')))

    def test_arithmetic_and_boolean_precedence(self):
        query = parse('SELECT price + qty * 2 - 1 FROM t WHERE NOT a = 1 OR b = 2 AND c < 3')
        self.assertEqual(query.columns[0].expression, BinaryOp('-',
            BinaryOp('+', ColumnRef('price'), BinaryOp('*', ColumnRef('qty'), Literal(2))), Literal(1)))
        self.assertEqual(query.where, BinaryOp('OR', UnaryOp('NOT', BinaryOp('=', ColumnRef('a'), Literal(1))),
            BinaryOp('AND', BinaryOp('=', ColumnRef('b'), Literal(2)), BinaryOp('<', ColumnRef('c'), Literal(3)))))

    def test_parentheses_unary_signs_and_left_associativity(self):
        query = parse('SELECT -(a + 1) * +b, 10 / 2 / 5, 9 % 2 FROM t WHERE (a=1 OR b=2) AND c=3')
        self.assertEqual(query.columns[0].expression,
                         BinaryOp('*', UnaryOp('-', BinaryOp('+', ColumnRef('a'), Literal(1))), UnaryOp('+', ColumnRef('b'))))
        self.assertEqual(query.columns[1].expression, BinaryOp('/', BinaryOp('/', Literal(10), Literal(2)), Literal(5)))
        self.assertEqual(query.where.operator, 'AND')
        self.assertEqual(query.where.left.operator, 'OR')

    def test_between_does_not_consume_boolean_and(self):
        query = parse('SELECT id FROM t WHERE price NOT BETWEEN 1+2 AND 10 AND active=TRUE')
        self.assertEqual(query.where.operator, 'AND')
        self.assertEqual(query.where.left, Between(ColumnRef('price'), BinaryOp('+', Literal(1), Literal(2)), Literal(10), True))

    def test_in_like_and_null_predicates(self):
        cases = {
            "id IN (1,2,NULL)": InList(ColumnRef('id'), (Literal(1), Literal(2), Literal(None))),
            "id NOT IN (1,2)": InList(ColumnRef('id'), (Literal(1), Literal(2)), True),
            "name LIKE 'a%'": BinaryOp('LIKE', ColumnRef('name'), Literal('a%')),
            "name NOT LIKE '_x'": BinaryOp('NOT LIKE', ColumnRef('name'), Literal('_x')),
            "name IS NULL": IsNull(ColumnRef('name')),
            "name IS NOT NULL": IsNull(ColumnRef('name'), True),
            "id <> 3": BinaryOp('!=', ColumnRef('id'), Literal(3)),
        }
        for clause, expected in cases.items():
            with self.subTest(clause=clause):
                self.assertEqual(parse('SELECT * FROM t WHERE ' + clause).where, expected)

    def test_aggregates_group_having_order_and_limit(self):
        query = parse('''SELECT category, COUNT(*) AS n, SUM(price * qty) AS total,
                               AVG(price), MIN(price), MAX(price), COUNT(DISTINCT name)
                        FROM products WHERE qty > 0 GROUP BY category
                        HAVING COUNT(*) >= 2 ORDER BY total DESC NULLS LAST, category ASC
                        LIMIT 10 OFFSET 5;''')
        self.assertEqual(query.columns[1].expression, AggregateCall('COUNT', Star()))
        self.assertEqual(query.columns[-1].expression, AggregateCall('COUNT', ColumnRef('name'), True))
        self.assertEqual(query.group_by, (ColumnRef('category'),))
        self.assertEqual(query.having.operator, '>=')
        self.assertEqual(query.order_by[0].direction, 'DESC')
        self.assertFalse(query.order_by[0].nulls_first)
        self.assertIsNone(query.order_by[1].nulls_first)
        self.assertEqual((query.limit, query.offset), (10, 5))

    def test_distinct_quoted_identifiers_and_case_normalization(self):
        query = parse('select distinct "Order"."Name", ID from "Order" order by "Name" nulls first')
        self.assertTrue(query.distinct)
        self.assertEqual(query.columns[0].expression, ColumnRef('Name', 'Order'))
        self.assertEqual(query.columns[1].expression, ColumnRef('id'))
        self.assertEqual(query.from_table.name, 'Order')
        self.assertTrue(query.order_by[0].nulls_first)

    def test_global_aggregate_and_order_expressions(self):
        query = parse('SELECT COUNT(*) FROM t HAVING COUNT(*) > 0 ORDER BY COUNT(*) DESC')
        self.assertEqual(query.group_by, ())
        self.assertIsInstance(query.order_by[0].expression, AggregateCall)
        self.assertEqual(parse('SELECT id FROM t OFFSET 2').offset, 2)

    def test_complete_statement_is_required(self):
        invalid = [
            '', 'SELECT', 'SELECT FROM t', 'SELECT id', 'SELECT id, FROM t',
            'SELECT * FROM', 'SELECT * FROM t WHERE', 'SELECT * FROM t WHERE a =',
            'SELECT * FROM t WHERE a = 1 = 2', 'SELECT * FROM t WHERE a IN ()',
            'SELECT * FROM t WHERE a BETWEEN 1 2', 'SELECT * FROM t WHERE a IS 1',
            'SELECT * FROM t WHERE (a=1', 'SELECT * FROM t ORDER id',
            'SELECT * FROM t ORDER BY id NULLS', 'SELECT * FROM t GROUP BY',
            'SELECT * FROM t ORDER BY id WHERE id=1', 'SELECT * FROM t LIMIT -1',
            'SELECT * FROM t LIMIT 1.5', 'SELECT * FROM t JOIN s',
            'SELECT * FROM t JOIN s ON', 'SELECT * FROM t LEFT JOIN s ON t.id=s.id',
            'SELECT SUM(*) FROM t', 'SELECT COUNT(DISTINCT *) FROM t',
            'SELECT SUM(COUNT(id)) FROM t', 'SELECT COUNT() FROM t',
            'SELECT id(1) FROM t', 'SELECT * AS all_columns FROM t',
            'SELECT * FROM t UNION SELECT * FROM s', 'SELECT * FROM (SELECT * FROM t)',
            'SELECT * FROM t; DELETE FROM t', 'SELECT * FROM t;;',
        ]
        for sql in invalid:
            with self.subTest(sql=sql), self.assertRaises(SQLParseError):
                parse(sql)


class TestMutationAndScriptParser(unittest.TestCase):
    def test_insert_with_columns_multiple_rows_and_signed_literals(self):
        query = parse("INSERT INTO Products (id,name,price,active) VALUES (-1,'O''Brien',+2.5,TRUE),(2,NULL,-3e2,FALSE)")
        self.assertEqual(query, InsertStatement('products', ('id', 'name', 'price', 'active'), (
            (Literal(-1), Literal("O'Brien"), Literal(2.5), Literal(True)),
            (Literal(2), Literal(None), Literal(-300.), Literal(False)),
        )))

    def test_insert_without_columns(self):
        query = parse("INSERT INTO t VALUES (1,'a'),(2,'b');")
        self.assertIsNone(query.columns)
        self.assertEqual(len(query.values), 2)

    def test_insert_rejects_mismatched_rows_and_invalid_values(self):
        invalid = ['INSERT t VALUES (1)', 'INSERT INTO t VALUES ()', 'INSERT INTO t () VALUES (1)',
                   'INSERT INTO t (a,a) VALUES (1,2)', 'INSERT INTO t (A,a) VALUES (1,2)',
                   'INSERT INTO t (a,b) VALUES (1)', 'INSERT INTO t VALUES (1),(2,3)',
                   'INSERT INTO t VALUES (id)', 'INSERT INTO t VALUES (1+2)', 'INSERT INTO t VALUES (-NULL)',
                   'INSERT INTO t VALUES (1),', 'INSERT INTO t VALUES (1,)']
        for sql in invalid:
            with self.subTest(sql=sql), self.assertRaises(SQLParseError):
                parse(sql)

    def test_delete_with_and_without_where(self):
        self.assertEqual(parse('DELETE FROM t;'), DeleteStatement(TableRef('t')))
        self.assertEqual(parse('DELETE FROM t AS x WHERE x.id = 1'),
                         DeleteStatement(TableRef('t', 'x'), BinaryOp('=', ColumnRef('id', 'x'), Literal(1))))

    def test_transaction_statements(self):
        for text, action in [('BEGIN', 'BEGIN'), ('BEGIN TRANSACTION', 'BEGIN'), ('COMMIT', 'COMMIT'),
                             ('END TRANSACTION', 'COMMIT'), ('ROLLBACK TRANSACTION', 'ROLLBACK')]:
            with self.subTest(text=text):
                self.assertEqual(parse(text), TransactionStatement(action))

    def test_scripts_respect_strings_comments_and_delimiters(self):
        script = """BEGIN; INSERT INTO t VALUES (1,'; -- text');
                    /* ; */ SELECT * FROM t; DELETE FROM t WHERE id=1; COMMIT; -- end"""
        statements = parse_script(script)
        self.assertEqual(len(statements), 5)
        self.assertEqual(statements[1].values[0][1], Literal('; -- text'))
        self.assertEqual(parse_script(' /* empty */ '), ())
        for sql in [';', 'BEGIN;;COMMIT', 'BEGIN COMMIT', 'SELECT * FROM t SELECT * FROM s']:
            with self.subTest(sql=sql), self.assertRaises(SQLParseError):
                parse_script(sql)

    def test_parse_script_is_all_or_error(self):
        with self.assertRaises(SQLParseError):
            parse_script('DELETE FROM t; SELECT FROM t;')


class TestASTAndDiagnostics(unittest.TestCase):
    def test_immutable_ast_and_json_serialization(self):
        query = parse("SELECT id FROM t WHERE name='café'")
        with self.assertRaises(FrozenInstanceError):
            query.limit = 4
        data = json.loads(json.dumps(query.to_dict()))
        self.assertEqual(data['type'], 'SelectStatement')
        self.assertEqual(data['where']['right'], {'type': 'Literal', 'value': 'café'})
        self.assertEqual(data['columns'][0]['expression']['name'], 'id')

    def test_syntax_error_line_column_and_source_pointer(self):
        sql = 'SELECT id\nFROM products\nWHERE price >= ;'
        with self.assertRaises(SQLParseError) as caught:
            parse(sql)
        error = caught.exception
        self.assertEqual((error.line, error.column), (3, 16))
        self.assertEqual(sql[error.offset], ';')
        self.assertIn('WHERE price >= ;', str(error))
        self.assertIn('^', str(error))

    def test_lexical_errors_are_distinguishable(self):
        with self.assertRaises(SQLLexError):
            parse("SELECT * FROM t WHERE name='unclosed")

    def test_reusable_parser_and_nested_limit(self):
        parser = Parser('SELECT id FROM t;')
        self.assertEqual(parser.parse(), parser.parse())
        self.assertEqual(parser.parse_script(), (parser.parse(),))
        self.assertEqual(parse('SELECT ' + '(' * 30 + 'id' + ')' * 30 + ' FROM t').columns[0].expression, ColumnRef('id'))
        with self.assertRaises(SQLParseError):
            parse('SELECT ' + '(' * 65 + 'id' + ')' * 65 + ' FROM t')
        with self.assertRaises(SQLParseError):
            Parser('SELECT (((id))) FROM t', max_depth=2).parse()

    def test_long_lists_and_flat_predicates(self):
        query = parse('SELECT ' + ','.join(f'c{i}' for i in range(500)) + ' FROM t')
        self.assertEqual(len(query.columns), 500)
        query = parse('SELECT * FROM t WHERE ' + ' AND '.join(f'id={i}' for i in range(300)))
        self.assertEqual(query.where.operator, 'AND')


if __name__ == "__main__":
    unittest.main()
