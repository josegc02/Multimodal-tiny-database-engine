-- psql -v ON_ERROR_STOP=1 -f postgres_text/examples.sql
-- Requiere haber cargado noticias_1000 con python -m postgres_text.load.
SELECT id, ts_rank(full_text, query, 0) AS score
FROM texto.noticias_1000,
     to_tsquery('pg_catalog.spanish', 'inflación | precios | alimentos') AS query
WHERE full_text @@ query
ORDER BY score DESC, id ASC LIMIT 10;

-- AND explícito como en el laboratorio; no es el OR usado por el benchmark.
SELECT id, contenido
FROM texto.noticias_1000
WHERE full_text @@ to_tsquery('pg_catalog.spanish', 'banca & digital');

EXPLAIN (ANALYZE, BUFFERS)
SELECT id, ts_rank(full_text, query, 0) AS score
FROM texto.noticias_1000,
     to_tsquery('pg_catalog.spanish', 'robótica | automatización | industrial') AS query
WHERE full_text @@ query
ORDER BY score DESC, id ASC LIMIT 10;
