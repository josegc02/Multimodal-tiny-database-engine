"""GIN en una tabla temporal de sesión: las tablas de #50 no se modifican."""

from postgres_text.client import connect
from postgres_text.queries import query_expression
from benchmarks.text_disk import postgres_disk
from benchmarks.text_memory import backend_memory

QUERY = """SELECT id, ts_rank(full_text, q.query, 0) AS score
FROM pg_temp.bench_news, to_tsquery('pg_catalog.spanish', %s) AS q(query)
WHERE full_text @@ q.query ORDER BY score DESC, id ASC LIMIT 10"""


class PostgresRun:
    def __init__(self, dsn, container):
        self.dsn, self.container = dsn, container

    def __enter__(self):
        self.connection = connect(self.dsn)
        try:
            self.connection.execute("SET max_parallel_workers_per_gather=0")
            self.pid = self.connection.execute("SELECT pg_backend_pid()").fetchone()[0]
            self.initial_memory = self.memory()
            self.version = self.connection.info.server_version
            return self
        except BaseException:
            self.connection.close()
            raise

    def __exit__(self, *exc):
        self.connection.close()

    def memory(self):
        return backend_memory(self.container, self.pid)

    def load(self, csv):
        with self.connection.transaction():
            self.connection.execute("""CREATE TEMP TABLE bench_news (
                id integer PRIMARY KEY, url text NOT NULL, contenido text NOT NULL,
                categoria text NOT NULL, tema text NOT NULL,
                full_text tsvector GENERATED ALWAYS AS
                (to_tsvector('pg_catalog.spanish'::regconfig,contenido)) STORED
            ) ON COMMIT PRESERVE ROWS""")
            with self.connection.cursor() as cursor:
                with cursor.copy("COPY bench_news (id,url,contenido,categoria,tema) "
                                 "FROM STDIN WITH (FORMAT CSV,HEADER TRUE,ENCODING 'UTF8')") as copy:
                    with csv.open("rb") as stream:
                        while block := stream.read(1024 * 1024):
                            copy.write(block)

    def build(self):
        self.connection.execute("CREATE INDEX bench_news_gin ON bench_news USING GIN (full_text)")

    def analyze(self):
        self.connection.execute("ANALYZE bench_news")

    def search(self, query):
        return self.connection.execute(QUERY, (query_expression(query),)).fetchall()

    def explain(self, query):
        return self.connection.execute("EXPLAIN (FORMAT JSON) " + QUERY,
                                       (query_expression(query),)).fetchone()[0]

    def disk(self):
        return postgres_disk(self.connection)

    def counters(self):
        return {"postings_read": None, "pages_read": None}
