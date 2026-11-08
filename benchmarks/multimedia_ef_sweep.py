"""Barrido de ef_search en HNSW con los vectores y consultas de una corrida de multimedia_compare.

Reutiliza las cachés vectors_<features>_<tamaño>.npz que dejó el benchmark (no extrae SIFT de nuevo),
construye el índice una vez por tamaño y mide Recall@10 y la latencia para varios ef_search.

    python -m benchmarks.multimedia_ef_sweep --dataset-dir datasets/coco_subsets \\
        --results benchmarks/results/smoke/multimedia --output hnsw_ef_sweep.json
"""

import argparse
import json
import time
from pathlib import Path

import numpy as np

from benchmarks.multimedia_compare import K, exact_neighbors
from benchmarks.multimedia_data import load_subset
from engine.indexes.hnsw import HNSWIndex


def sweep(dataset_dir: Path, results: Path, size: int, ef_values: list[int], features: str = "bovw"):
    filenames, queries = load_subset(dataset_dir / f"coco{size // 1000}k", size)
    with np.load(results / f"vectors_{features}_{size}.npz", allow_pickle=False) as saved:
        vectors = saved["vectors"]
    index = HNSWIndex(M=8, ef_construction=50, metric="euclidean", seed=42)
    started = time.perf_counter()
    for i, vector in enumerate(vectors):
        index.insert(i, vector)
    build = time.perf_counter() - started
    ids = {name: i for i, name in enumerate(filenames)}
    truths = []
    for query in queries:
        qid = ids[query["query_file"]]
        truths.append((qid, exact_neighbors(vectors, vectors[qid], qid, "euclidean")))
    rows = []
    for ef in ef_values:
        recalls, seconds = [], []
        for qid, truth in truths:
            started = time.perf_counter()
            result = index.search(vectors[qid], k=K + 1, ef_search=ef)
            seconds.append(time.perf_counter() - started)
            found = [i for i, _ in result.matches if i != qid][:K]
            recalls.append(len(set(found) & set(truth)) / K)
        rows.append({"size": size, "ef_search": ef, "queries": len(truths), "build_seconds": build,
                     "mean_query_ms": 1000 * float(np.mean(seconds)),
                     "recall_at_10": float(np.mean(recalls))})
        print(rows[-1], flush=True)
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset-dir", type=Path, default=Path("datasets/coco_subsets"))
    parser.add_argument("--results", type=Path, required=True, help="Salida de multimedia_compare (con las cachés .npz)")
    parser.add_argument("--sizes", type=int, nargs="+", default=[10000, 100000])
    parser.add_argument("--ef", type=int, nargs="+", default=[50, 100, 200, 400, 800])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    rows = []
    for size in args.sizes:
        rows.extend(sweep(args.dataset_dir, args.results, size, args.ef))
        args.output.write_text(json.dumps(rows, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
