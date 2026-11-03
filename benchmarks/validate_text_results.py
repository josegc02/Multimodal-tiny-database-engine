"""Auditar cobertura y recalcular relevancia de los rankings exportados."""

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path

from benchmarks.text_metrics import relevance_at_k, validate_ranking
from benchmarks.text_workload import read_workload


def read(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def key(row):
    return int(row["size"]), row["technique"], int(row["repetition"])


def validate(directory, datasets):
    directory, datasets = Path(directory), Path(datasets)
    metadata = json.loads((directory / "metadata.json").read_text())
    if not metadata["complete"]:
        raise ValueError("Corrida incompleta")
    techniques = ("TF-IDF", "BM25") if metadata["partial"] else ("TF-IDF", "BM25", "GIN")
    expected = {(size, technique, rep) for size in metadata["sizes"] for technique in techniques
                for rep in range(1, metadata["repetitions"] + 1)}
    builds = read(directory / "build_runs.csv")
    if len(builds) != len(expected) or {key(row) for row in builds} != expected:
        raise ValueError("Cobertura incompleta de construcciones")
    for row in builds:
        for metric in ("load_seconds", "build_seconds", "rss_peak_bytes", "index_bytes", "total_bytes"):
            if not math.isfinite(float(row[metric])) or float(row[metric]) <= 0:
                raise ValueError(f"Medición inválida: {metric}")
    workloads = {size: read_workload(datasets, size, metadata["seed"]) for size in metadata["sizes"]}
    expected_queries = {(*run, q["query_id"]) for run in expected for q in workloads[run[0]][0]}
    queries = read(directory / "query_runs.csv")
    if len(queries) != len(expected_queries) or {(*key(row), row["query_id"]) for row in queries} != expected_queries:
        raise ValueError("Cobertura incompleta de consultas")
    rankings = defaultdict(list)
    for row in read(directory / "rankings.csv"):
        group = (*key(row), row["query_id"])
        if group not in expected_queries:
            raise ValueError("Ranking sin consulta")
        rankings[group].append(row)
    for query in queries:
        size, technique, rep = key(query)
        rows = sorted(rankings[(size, technique, rep, query["query_id"])], key=lambda row: int(row["rank"]))
        if [int(row["rank"]) for row in rows] != list(range(1, len(rows) + 1)):
            raise ValueError("Posiciones inválidas")
        pairs = [(int(row["doc_id"]), float(row["score"])) for row in rows]
        validate_ranking(pairs, size)
        relevant = workloads[size][1][query["query_id"]]
        metrics = relevance_at_k([i for i, _ in pairs], relevant)
        for metric, value in metrics.items():
            actual = None if query[metric] == "NA" else float(query[metric])
            if actual != value:
                raise ValueError(f"Relevancia inconsistente: {metric}")
        if any(int(row["relevant"]) != int(int(row["doc_id"]) in relevant) for row in rows):
            raise ValueError("Etiqueta incorrecta en ranking")
    return {"runs": len(builds), "queries": len(queries), "ranked_documents": sum(map(len, rankings.values()))}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--datasets", type=Path, default=Path("datasets/text/generated"))
    args = parser.parse_args()
    print(json.dumps(validate(args.directory, args.datasets), indent=2))
