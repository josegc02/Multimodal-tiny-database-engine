"""Parser descendente recursivo del dialecto definido en docs/sql_grammar.ebnf.

parse() exige una sentencia completa; parse_script() separa sentencias con ';'.
El resultado es un AST: no se usa eval, no se consulta storage y no se ejecuta SQL.
"""

from contextlib import contextmanager

from engine.query.ast import (
    AggregateCall, Between, BinaryOp, ColumnRef, DeleteStatement, InList,
    InsertStatement, IsNull, Join, Literal, OrderByItem, SelectItem,
    SelectStatement, Star, Statement, TableRef, TransactionStatement, UnaryOp,
)
from engine.query.errors import SQLParseError
from engine.query.lexer import tokenize

AGGREGATES = {"COUNT", "SUM", "AVG", "MIN", "MAX"}
COMPARISONS = {"=", "!=", "<>", "<", "<=", ">", ">="}


class Parser:
    def __init__(self, source: str, *, max_depth: int = 64):
        if type(max_depth) is not int or not 1 <= max_depth <= 64:
            raise ValueError("max_depth debe estar entre 1 y 64")
        self.source = source
        self.tokens = tokenize(source)
        self.max_depth = max_depth
        self._reset()

    def _reset(self):
        self.position = 0
        self.depth = 0
        self.aggregate_depth = 0

    def _peek(self, ahead=0):
        return self.tokens[min(self.position + ahead, len(self.tokens) - 1)]

    def _advance(self):
        token = self._peek()
        if token.kind != "EOF":
            self.position += 1
        return token

    def _match(self, *kinds):
        return self._advance() if self._peek().kind in kinds else None

    def _error(self, message, token=None):
        token = token or self._peek()
        raise SQLParseError(message, self.source, token.offset, token.line, token.column)

    def _expect(self, kind):
        token = self._match(kind)
        if token is None:
            found = repr(self._peek().lexeme) if self._peek().kind != "EOF" else "fin de entrada"
            self._error(f"Se esperaba {kind}; se encontró {found}")
        return token

    @contextmanager
    def _nested(self):
        self.depth += 1
        try:
            if self.depth > self.max_depth:
                self._error(f"Se excedió el límite de anidamiento ({self.max_depth})")
            yield
        finally:
            self.depth -= 1

    def parse(self) -> Statement:
        self._reset()
        statement = self._statement()
        self._match(";")
        self._expect("EOF")
        return statement

    def parse_script(self) -> tuple[Statement, ...]:
        self._reset()
        statements = []
        while self._peek().kind != "EOF":
            statements.append(self._statement())
            if not self._match(";"):
                self._expect("EOF")
        return tuple(statements)

    def _statement(self):
        if self._match("SELECT"):
            return self._select()
        if self._match("INSERT"):
            return self._insert()
        if self._match("DELETE"):
            return self._delete()
        if token := self._match("BEGIN", "COMMIT", "END", "ROLLBACK"):
            self._match("TRANSACTION")
            return TransactionStatement("COMMIT" if token.kind == "END" else token.kind)
        self._error("Se esperaba SELECT, INSERT, DELETE, BEGIN, COMMIT, END o ROLLBACK")

    def _identifier(self):
        return self._expect("IDENTIFIER").value

    def _alias(self):
        if self._match("AS"):
            return self._identifier()
        if self._peek().kind == "IDENTIFIER":
            return self._identifier()
        return None

    def _table(self):
        name = self._identifier()
        return TableRef(name, self._alias())

    def _comma_list(self, parse_item):
        result = [parse_item()]
        while self._match(","):
            result.append(parse_item())
        return tuple(result)

    def _select_item(self):
        if self._match("*"):
            return SelectItem(Star())
        if (self._peek().kind == "IDENTIFIER" and self._peek(1).kind == "."
                and self._peek(2).kind == "*"):
            table = self._identifier()
            self._advance()
            self._advance()
            return SelectItem(Star(table))
        expression = self._expression()
        return SelectItem(expression, self._alias())

    def _select(self):
        distinct = self._match("DISTINCT") is not None
        columns = self._comma_list(self._select_item)
        self._expect("FROM")
        table = self._table()
        joins = []
        while self._peek().kind in {"JOIN", "INNER"}:
            self._match("INNER")
            self._expect("JOIN")
            joined = self._table()
            self._expect("ON")
            joins.append(Join(joined, self._expression()))
        where = self._expression() if self._match("WHERE") else None
        group_by = ()
        if self._match("GROUP"):
            self._expect("BY")
            group_by = self._comma_list(self._expression)
        having = self._expression() if self._match("HAVING") else None
        order_by = ()
        if self._match("ORDER"):
            self._expect("BY")
            order_by = self._comma_list(self._order_item)
        limit = self._expect("INTEGER").value if self._match("LIMIT") else None
        offset = self._expect("INTEGER").value if self._match("OFFSET") else None
        return SelectStatement(columns, table, tuple(joins), where, group_by,
                               having, order_by, distinct, limit, offset)

    def _order_item(self):
        expression = self._expression()
        direction = self._match("ASC", "DESC")
        nulls_first = None
        if self._match("NULLS"):
            placement = self._match("FIRST", "LAST")
            if placement is None:
                self._error("NULLS requiere FIRST o LAST")
            nulls_first = placement.kind == "FIRST"
        return OrderByItem(expression, direction.kind if direction else "ASC", nulls_first)

    def _insert(self):
        self._expect("INTO")
        table = self._identifier()
        columns = None
        if self._match("("):
            columns = self._comma_list(self._identifier)
            if len(set(columns)) != len(columns):
                self._error("INSERT contiene columnas repetidas")
            self._expect(")")
        self._expect("VALUES")
        rows = self._comma_list(self._value_row)
        width = len(columns) if columns is not None else len(rows[0])
        if any(len(row) != width for row in rows):
            self._error("Las filas de VALUES deben coincidir en cantidad de valores con las columnas")
        return InsertStatement(table, columns, rows)

    def _value_row(self):
        self._expect("(")
        row = self._comma_list(self._literal)
        self._expect(")")
        return row

    def _literal(self):
        sign = self._match("+", "-")
        if token := self._match("INTEGER", "FLOAT"):
            return Literal(-token.value if sign and sign.kind == "-" else token.value)
        if sign is not None:
            self._error("El signo debe preceder a un literal numérico")
        if token := self._match("STRING"):
            return Literal(token.value)
        if token := self._match("NULL", "TRUE", "FALSE"):
            return Literal({"NULL": None, "TRUE": True, "FALSE": False}[token.kind])
        self._error("Se esperaba un literal numérico, string, NULL, TRUE o FALSE")

    def _delete(self):
        self._expect("FROM")
        table = self._table()
        where = self._expression() if self._match("WHERE") else None
        return DeleteStatement(table, where)

    def _expression(self):
        left = self._and()
        while self._match("OR"):
            left = BinaryOp("OR", left, self._and())
        return left

    def _and(self):
        left = self._not()
        while self._match("AND"):
            left = BinaryOp("AND", left, self._not())
        return left

    def _not(self):
        count = 0
        while self._match("NOT"):
            count += 1
        expression = self._predicate()
        for _ in range(count):
            expression = UnaryOp("NOT", expression)
        return expression

    def _predicate(self):
        left = self._additive()
        if token := self._match(*COMPARISONS):
            return BinaryOp("!=" if token.kind == "<>" else token.kind, left, self._additive())
        if self._match("IS"):
            negated = self._match("NOT") is not None
            self._expect("NULL")
            return IsNull(left, negated)
        negated = False
        if self._peek().kind == "NOT" and self._peek(1).kind in {"BETWEEN", "IN", "LIKE"}:
            self._advance()
            negated = True
        if self._match("BETWEEN"):
            lower = self._additive()
            self._expect("AND")
            return Between(left, lower, self._additive(), negated)
        if self._match("IN"):
            self._expect("(")
            with self._nested():
                values = self._comma_list(self._expression)
                self._expect(")")
            return InList(left, values, negated)
        if self._match("LIKE"):
            return BinaryOp("NOT LIKE" if negated else "LIKE", left, self._additive())
        return left

    def _additive(self):
        left = self._multiplicative()
        while token := self._match("+", "-"):
            left = BinaryOp(token.kind, left, self._multiplicative())
        return left

    def _multiplicative(self):
        left = self._unary()
        while token := self._match("*", "/", "%"):
            left = BinaryOp(token.kind, left, self._unary())
        return left

    def _unary(self):
        operators = []
        while token := self._match("+", "-"):
            operators.append(token.kind)
        expression = self._primary()
        for operator in reversed(operators):
            expression = UnaryOp(operator, expression)
        return expression

    def _primary(self):
        if self._match("("):
            with self._nested():
                expression = self._expression()
                self._expect(")")
            return expression
        if self._peek().kind in {"INTEGER", "FLOAT", "STRING", "NULL", "TRUE", "FALSE"}:
            return self._literal()
        if self._peek().kind in AGGREGATES:
            return self._aggregate()
        if self._peek().kind == "IDENTIFIER":
            first = self._identifier()
            if self._match("."):
                return ColumnRef(self._identifier(), first)
            return ColumnRef(first)
        self._error("Se esperaba una columna, literal, agregado o expresión entre paréntesis")

    def _aggregate(self):
        function = self._advance()
        if self.aggregate_depth:
            self._error("No se permiten agregados anidados", function)
        self._expect("(")
        distinct = self._match("DISTINCT") is not None
        self.aggregate_depth += 1
        try:
            with self._nested():
                if self._match("*"):
                    if function.kind != "COUNT" or distinct:
                        self._error("Solo COUNT(*) admite '*' como argumento")
                    argument = Star()
                else:
                    argument = self._expression()
                self._expect(")")
        finally:
            self.aggregate_depth -= 1
        return AggregateCall(function.kind, argument, distinct)


def parse(source: str) -> Statement:
    return Parser(source).parse()


def parse_script(source: str) -> tuple[Statement, ...]:
    return Parser(source).parse_script()
