"""Lexer SQL sin dependencias: keywords, identificadores, literales y operadores."""

from dataclasses import dataclass
import math
import re

from engine.query.errors import SQLLexError

KEYWORDS = frozenset("""
SELECT DISTINCT FROM WHERE INSERT INTO VALUES DELETE AS
JOIN INNER ON GROUP BY HAVING ORDER ASC DESC NULLS FIRST LAST LIMIT OFFSET
AND OR NOT IS NULL TRUE FALSE BETWEEN IN LIKE
COUNT SUM AVG MIN MAX BEGIN TRANSACTION COMMIT END ROLLBACK
CREATE DROP ALTER UPDATE SET TABLE LEFT RIGHT FULL OUTER CROSS UNION EXISTS
INDEX USING HASH BTREE INT FLOAT STR VARCHAR
""".split())
NUMBER = re.compile(r"(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")


@dataclass(frozen=True)
class Token:
    kind: str
    lexeme: str
    value: object
    offset: int
    line: int
    column: int


class Lexer:
    def __init__(self, source: str):
        if not isinstance(source, str):
            raise TypeError("SQL debe ser un string")
        self.source = source
        self.offset = 0
        self.line = 1
        self.column = 1

    def _advance(self, count=1):
        text = self.source[self.offset:self.offset + count]
        self.offset += count
        if "\n" in text:
            self.line += text.count("\n")
            self.column = len(text.rsplit("\n", 1)[1]) + 1
        else:
            self.column += count

    def _error(self, message, start=None):
        offset, line, column = start or (self.offset, self.line, self.column)
        raise SQLLexError(message, self.source, offset, line, column)

    def _quoted(self, quote, start):
        self._advance()
        value = []
        while self.offset < len(self.source):
            char = self.source[self.offset]
            self._advance()
            if char == quote:
                if self.source[self.offset:self.offset + 1] == quote:
                    value.append(quote)
                    self._advance()
                else:
                    if quote == '"' and not value:
                        self._error("El identificador entre comillas no puede estar vacío", start)
                    return "".join(value)
            else:
                value.append(char)
        self._error("Literal o identificador sin comilla de cierre", start)

    def _block_comment(self):
        start = (self.offset, self.line, self.column)
        self._advance(2)
        depth = 1
        while self.offset < len(self.source):
            pair = self.source[self.offset:self.offset + 2]
            if pair == "/*":
                depth += 1
                self._advance(2)
            elif pair == "*/":
                depth -= 1
                self._advance(2)
                if not depth:
                    return
            else:
                self._advance()
        self._error("Comentario de bloque sin cierre", start)

    def tokenize(self) -> list[Token]:
        # Permite volver a tokenizar con la misma instancia.
        self.offset, self.line, self.column = 0, 1, 1
        tokens = []
        while self.offset < len(self.source):
            char = self.source[self.offset]
            pair = self.source[self.offset:self.offset + 2]
            if char.isspace():
                self._advance()
                continue
            if pair == "--":
                end = self.source.find("\n", self.offset)
                self._advance((len(self.source) if end == -1 else end) - self.offset)
                continue
            if pair == "/*":
                self._block_comment()
                continue
            start = (self.offset, self.line, self.column)
            if char in "'\"":
                value = self._quoted(char, start)
                kind = "STRING" if char == "'" else "IDENTIFIER"
            elif char in "0123456789" or (char == "." and self.source[self.offset + 1:self.offset + 2] in tuple("0123456789")):
                match = NUMBER.match(self.source, self.offset)
                text = match.group()
                self._advance(len(text))
                following = self.source[self.offset:self.offset + 1]
                if following and (following.isalnum() or following in "_."):
                    self._error("Literal numérico inválido", start)
                kind = "FLOAT" if any(c in text for c in ".eE") else "INTEGER"
                try:
                    value = float(text) if kind == "FLOAT" else int(text)
                except ValueError:
                    self._error("Literal numérico fuera del rango admitido", start)
                if kind == "FLOAT" and not math.isfinite(value):
                    self._error("El literal float debe ser finito", start)
            elif match := IDENTIFIER.match(self.source, self.offset):
                text = match.group()
                self._advance(len(text))
                kind = text.upper() if text.upper() in KEYWORDS else "IDENTIFIER"
                value = text.lower() if kind == "IDENTIFIER" else kind
            elif pair in {"<=", ">=", "!=", "<>"}:
                self._advance(2)
                kind = value = pair
            elif char in "(),;.*+-/%=<>":
                self._advance()
                kind = value = char
            else:
                self._error(f"Carácter no reconocido: {char!r}")
            tokens.append(Token(kind, self.source[start[0]:self.offset], value, *start))
        tokens.append(Token("EOF", "", None, self.offset, self.line, self.column))
        return tokens


def tokenize(source: str) -> list[Token]:
    return Lexer(source).tokenize()
