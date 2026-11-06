"""Reconoce palabras clave SQL fuera de comentarios y cadenas."""

import re


_TOKEN = re.compile(r"--[^\n]*|/\*[\s\S]*?(?:\*/|\Z)|'(?:''|[^'])*(?:'|\Z)|\"(?:\"\"|[^\"])*(?:\"|\Z)|[A-Za-z_][A-Za-z_0-9$]*|\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b")
_TYPES = frozenset("INT INTEGER BIGINT FLOAT DOUBLE REAL VARCHAR CHAR TEXT BOOLEAN DATE TIMESTAMP POINT IMAGE AUDIO".split())
_KEYWORDS = frozenset("""
SELECT FROM WHERE AND OR NOT IN IS NULL LIKE BETWEEN EXISTS AS DISTINCT ALL
INSERT INTO VALUES UPDATE SET DELETE CREATE TABLE INDEX ON USING DROP ALTER
PRIMARY KEY FOREIGN REFERENCES CHECK UNIQUE DEFAULT BEGIN TRANSACTION COMMIT
ROLLBACK SAVEPOINT RELEASE GROUP BY HAVING ORDER ASC DESC LIMIT OFFSET JOIN
INNER LEFT RIGHT OUTER CROSS FULL NATURAL UNION INTERSECT EXCEPT CASE WHEN THEN
ELSE END COUNT SUM AVG MIN MAX TRUE FALSE COPY WITH FORMAT HEADER DELIMITER
EXPLAIN ANALYZE SEQUENTIAL HEAP BTREE HASH RTREE SPIMI LANGUAGE MATCH SCORE
TF_IDF BM25 POINT DISTANCE WITHIN POLYGON EUCLIDEAN HAVERSINE IMAGE AUDIO
SIMILAR_TO SIMILARITY_SCORE IVF HNSW METRIC COSINE DOT
""".split())


def keyword_spans(text):
    """Devuelve intervalos (inicio, fin) de keywords, ignorando strings y comentarios."""
    return [(match.start(), match.end()) for match in _TOKEN.finditer(text)
            if match[0][0].isalpha() or match[0][0] == "_"
            if match[0].upper() in _KEYWORDS]


def syntax_spans(text):
    """Intervalos de palabras clave, cadenas y comentarios."""
    for match in _TOKEN.finditer(text):
        token = match[0]
        if token.startswith(("--", "/*")):
            kind = "comment"
        elif token.startswith("'"):
            kind = "string"
        elif token[0].isdigit():
            kind = "number"
        elif token.upper() in _TYPES:
            kind = "type"
        elif token.upper() in _KEYWORDS:
            kind = "keyword"
        else:
            continue
        yield kind, match.start(), match.end()
