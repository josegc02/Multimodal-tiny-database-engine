"""Espacio persistente; excluye el CSV original y temporales de construcción."""


def engine_disk(directory):
    index = sum(path.stat().st_size for path in directory.glob("*.spimi*"))
    data = sum(path.stat().st_size for pattern in ("*.db", "*.text") for path in directory.glob(pattern))
    return {"index_bytes": index, "total_bytes": data + index}


def postgres_disk(connection):
    row = connection.execute("SELECT pg_relation_size('pg_temp.bench_news_gin'), "
                             "pg_total_relation_size('pg_temp.bench_news')").fetchone()
    return {"index_bytes": row[0], "total_bytes": row[1]}
