"""Comparación IVF/HNSW en vectores de imágenes reales, k-NN exacto como referencia."""

import argparse
import csv
import json
import math
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

from benchmarks.multimedia_data import FEATURES, extract_vectors, load_subset

K = 10
SIZES = (1000, 10000, 100000)
METRICS = ("euclidean", "cosine")
INDEXES = ("IVF", "HNSW")


def exact_neighbors(vectors: np.ndarray, query: np.ndarray, query_id: int, metric: str,
                    usable: np.ndarray | None = None) -> list[int]:
    if metric == "euclidean":
        scores = np.sum((vectors - query) ** 2, axis=1)
    else:
        norms = np.linalg.norm(vectors, axis=1) * np.linalg.norm(query)
        with np.errstate(divide="ignore", invalid="ignore"):
            scores = -(vectors @ query) / norms
    if usable is not None:
        scores[~usable] = np.inf
    scores[query_id] = np.inf
    return np.lexsort((np.arange(len(vectors)), scores))[:K].tolist()


def run_trial(directory: Path, size: int, metric: str, technique: str, cache: Path,
              features: str | None = None):
    from benchmarks.text_memory import process_memory
    from engine.indexes.hnsw import HNSWIndex
    from engine.indexes.ivf import IVFIndex

    filenames, queries = load_subset(directory, size)
    vectors = extract_vectors(directory, filenames, cache, features)
    # El coseno no está definido para el vector nulo (imagen sin palabras visuales):
    # esas imágenes no se indexan ni cuentan como vecinos, igual que en el motor.
    usable = np.ones(len(vectors), dtype=bool)
    if metric == "cosine":
        usable = np.linalg.norm(vectors, axis=1) > 0
    ids = {name: i for i, name in enumerate(filenames)}
    nlist = max(1, round(math.sqrt(size)))
    nprobe = max(1, round(math.sqrt(nlist)))
    index = (IVFIndex(nlist, metric=metric, seed=42) if technique == "IVF"
             else HNSWIndex(M=8, ef_construction=50, metric=metric, seed=42))
    initial = process_memory()["VmRSS"]
    started = time.perf_counter()
    if technique == "IVF":
        index.train({i: vector for i, vector in enumerate(vectors) if usable[i]})
    else:
        for i, vector in enumerate(vectors):
            if usable[i]:
                index.insert(i, vector)
    build_seconds = time.perf_counter() - started
    rows = []
    skipped = 0
    for query in queries:
        qid = ids[query["query_file"]]
        if not usable[qid]:
            skipped += 1
            continue
        qvector = vectors[qid]
        truth = exact_neighbors(vectors, qvector, qid, metric, usable)
        started = time.perf_counter()
        result = (index.search(qvector, k=K + 1, nprobe=nprobe) if technique == "IVF"
                  else index.search(qvector, k=K + 1, ef_search=50))
        seconds = time.perf_counter() - started
        found = [i for i, _ in result.matches if i != qid][:K]
        if len(set(found)) != len(found):
            raise ValueError("El índice devolvió IDs duplicados")
        rows.append({"size": size, "metric": metric, "technique": technique,
                     "query_file": query["query_file"], "category": query["category_name"],
                     "query_seconds": seconds, "recall_at_10": len(set(found) & set(truth)) / K,
                     "exact_files": [filenames[i] for i in truth],
                     "found_files": [filenames[i] for i in found]})
    peak = process_memory()["VmHWM"]
    summary = {"size": size, "metric": metric, "technique": technique,
               "queries": len(rows), "skipped_queries": skipped,
               "excluded_vectors": int(np.count_nonzero(~usable)), "build_seconds": build_seconds,
               "mean_query_seconds": float(np.mean([r["query_seconds"] for r in rows])),
               "mean_recall_at_10": float(np.mean([r["recall_at_10"] for r in rows])),
               "rss_initial_bytes": initial, "rss_peak_bytes": peak,
               "nlist": nlist if technique == "IVF" else None,
               "nprobe": nprobe if technique == "IVF" else None,
               "M": 8 if technique == "HNSW" else None,
               "ef_construction": 50 if technique == "HNSW" else None,
               "ef_search": 50 if technique == "HNSW" else None}
    return summary, rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, default=Path("datasets/coco_subsets"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sizes", type=int, nargs="+", default=list(SIZES))
    parser.add_argument("--features", choices=FEATURES, default="bovw",
                        help="bovw: Bag of Visual Words K=256 (enunciado); sift-mean: promedio SIFT de #83")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.worker:
        request = json.load(sys.stdin)
        summary, rows = run_trial(Path(request["directory"]), request["size"], request["metric"],
                                  request["technique"], Path(request["cache"]), request.get("features"))
        print(json.dumps({"summary": summary, "rows": rows}, allow_nan=False))
        return
    if any(size not in SIZES for size in args.sizes):
        parser.error("--sizes admite 1000, 10000 y 100000")
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "features.json").write_text(json.dumps({"features": args.features}), encoding="utf-8")
    summaries, rows = [], []
    fallback_counts = {}
    for size in args.sizes:
        directory = args.dataset_dir / f"coco{size // 1000}k"
        filenames, _ = load_subset(directory, size)
        cache = args.output / f"vectors_{args.features}_{size}.npz"
        extract_vectors(directory, filenames, cache, args.features)
        with np.load(cache, allow_pickle=False) as saved:
            special = "empty_files" if args.features == "bovw" else "fallback_files"
            fallback_counts[str(size)] = len(saved[special]) if special in saved else 0
        (args.output / "fallback_counts.json").write_text(json.dumps(fallback_counts, indent=2), encoding="utf-8")
        for metric in METRICS:
            for technique in INDEXES:
                request = {"directory": str(directory), "size": size, "metric": metric,
                           "technique": technique, "cache": str(cache), "features": args.features}
                process = subprocess.run([sys.executable, "-m", "benchmarks.multimedia_compare",
                                          "--worker", "--output", str(args.output)],
                                         input=json.dumps(request), text=True, capture_output=True)
                if process.returncode:
                    raise RuntimeError(f"{size} {metric} {technique}: {process.stderr}")
                result = json.loads(process.stdout)
                summaries.append(result["summary"])
                rows.extend(result["rows"])
                print(f"{size} {metric} {technique}: Recall@10={result['summary']['mean_recall_at_10']:.3f}", flush=True)
    for name, data in (("summary.csv", summaries),):
        with (args.output / name).open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(data[0]))
            writer.writeheader()
            writer.writerows(data)
    (args.output / "queries.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    from benchmarks.multimedia_gallery import write_gallery
    from benchmarks.multimedia_plots import plot_results
    from benchmarks.multimedia_report import write_report

    plot_results(args.output)
    write_gallery(args.output, args.dataset_dir)
    write_report(args.output)


if __name__ == "__main__":
    main()
