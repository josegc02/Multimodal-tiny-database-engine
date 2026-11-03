"""Lectura de consultas y juicios ya validados por el protocolo de #49."""

import csv
import random
from pathlib import Path


def read_workload(directory, size, seed):
    directory = Path(directory)
    with (directory / "queries.csv").open(encoding="utf-8", newline="") as stream:
        queries = list(csv.DictReader(stream))
    for query in queries:
        query["words"] = int(query["words"])
    relevant = {q["query_id"]: set() for q in queries}
    with (directory / f"qrels_{size}.csv").open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            if int(row["relevance"]) > 0:
                relevant[row["query_id"]].add(int(row["doc_id"]))
    random.Random(seed).shuffle(queries)
    return queries, relevant
