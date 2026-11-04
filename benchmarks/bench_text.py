"""python -m benchmarks.bench_text: experimento reproducible de la Parte 3."""

import json
import random
import subprocess
import sys
from datetime import datetime, timezone

from benchmarks.text_config import arguments
from benchmarks.text_metadata import environment
from benchmarks.text_output import write_csv, write_json
from benchmarks.text_summary import export_summaries
from benchmarks.text_validation import validate_bundle


def run_worker(request):
    process = subprocess.run([sys.executable, "-m", "benchmarks.text_worker"],
                             input=json.dumps(request), text=True, capture_output=True, timeout=1800)
    if process.returncode:
        raise RuntimeError(f"Worker {request['technique']} falló:\n{process.stderr}")
    return json.loads(process.stdout)


def main(argv=None):
    args = arguments(argv)
    bundle = validate_bundle(args.dataset_dir)
    if any(size not in bundle for size in args.sizes):
        raise ValueError("Un tamaño solicitado no existe en el bundle")
    args.output.mkdir(parents=True, exist_ok=False)
    corpus = json.loads((args.dataset_dir / "metadata.json").read_text(encoding="utf-8"))
    metadata = environment(args, corpus)
    write_json(args.output / "metadata.json", metadata)
    runs, queries, rankings, plans = [], [], [], []
    techniques = ["TF-IDF", "BM25"] + ([] if args.sin_postgres else ["GIN"])
    order = random.Random(args.seed)
    for size in args.sizes:
        for repetition in range(1, args.repetitions + 1):
            order.shuffle(techniques)
            for technique in techniques:
                print(f"[texto] N={size} rep={repetition} {technique}", flush=True)
                request = {"dataset_dir": str(args.dataset_dir.resolve()), "size": size,
                           "technique": technique, "repetition": repetition, "seed": args.seed,
                           "dsn": args.dsn, "container": args.container}
                result = run_worker(request)
                key = {"size": size, "technique": technique, "repetition": repetition}
                queries.extend({**key, **row} for row in result.pop("samples"))
                rankings.extend({**key, **row} for row in result.pop("rankings"))
                if "plans" in result:
                    plans.append({**key, "queries": result.pop("plans")})
                    metadata["postgres"] = {"version": result.pop("server_version"), "settings": result.pop("settings")}
                runs.append({**key, **result})
                # Checkpoint auditable: una interrupción no se anuncia como corrida completa.
                write_csv(args.output / "build_runs.csv", runs)
                write_csv(args.output / "query_runs.csv", queries)
                write_csv(args.output / "rankings.csv", rankings)
                write_json(args.output / "plans.json", plans)
    export_summaries(args.output, runs, queries)
    metadata["complete"] = True
    metadata["finished_utc"] = datetime.now(timezone.utc).isoformat()
    write_json(args.output / "metadata.json", metadata)


if __name__ == "__main__":
    main()
