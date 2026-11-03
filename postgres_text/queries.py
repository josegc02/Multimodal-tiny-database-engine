"""Consultas parametrizadas: OR de palabras y ranking nativo ts_rank."""

from engine.text.preprocessing import tokenizar
from postgres_text.schema import table_name


def query_expression(text):
    if not isinstance(text, str):
        raise ValueError("La consulta debe ser texto")
    # No interpretar &, |, !, pesos ni prefijos escritos por el usuario.
    words = dict.fromkeys(tokenizar(text))
    return " | ".join("'" + word.replace("\\", "\\\\").replace("'", "''") + "'" for word in words)


def ranked_statement(size, expression, top_k=10):
    from psycopg import sql

    name = table_name(size)
    if type(top_k) is not int or top_k < 0:
        raise ValueError("top_k debe ser un entero no negativo")
    statement = sql.SQL("""
        SELECT id, ts_rank(full_text, q.query, 0) AS score
        FROM texto.{}, to_tsquery('pg_catalog.spanish'::regconfig, %s) AS q(query)
        WHERE full_text @@ q.query
        ORDER BY score DESC, id ASC LIMIT %s
    """).format(sql.Identifier(name))
    return statement, (expression, top_k)


def search(connection, size, text, top_k=10):
    statement, params = ranked_statement(size, query_expression(text), top_k)
    if not params[0] or not top_k:
        return []
    return connection.execute(statement, params).fetchall()


def search_tsquery(connection, size, expression, top_k=10):
    """Sintaxis PostgreSQL explícita para ejercicios AND/OR del laboratorio."""
    statement, params = ranked_statement(size, expression, top_k)
    return connection.execute(statement, params).fetchall()


def explain(connection, size, text, top_k=10):
    """Plan elegido por PostgreSQL, sin forzar GIN ni ejecutar la consulta."""
    from psycopg import sql

    statement, params = ranked_statement(size, query_expression(text), top_k)
    return connection.execute(sql.SQL("EXPLAIN (FORMAT JSON) ") + statement, params).fetchone()[0]
