"""Proceso nuevo por técnica/repetición; protocolo JSON por stdin/stdout."""

import json
import sys
import tempfile
from pathlib import Path

from benchmarks.text_engine import EngineRun
from benchmarks.text_measure import timed
from benchmarks.text_memory import process_memory
from benchmarks.text_postgres import PostgresRun
from benchmarks.text_trials import query_trials
from benchmarks.text_workload import read_workload


def run(request):
    directory = Path(request["dataset_dir"])
    size, technique = request["size"], request["technique"]
    # Mismo orden de consultas para todas las técnicas de una repetición.
    queries, relevant = read_workload(directory, size, request["seed"] + request["repetition"])
    csv = directory / f"noticias_{size}.csv"
    initial = process_memory()
    with tempfile.TemporaryDirectory(prefix="bd2-text-bench-") as temp:
        adapter = (PostgresRun(request["dsn"], request["container"]) if technique == "GIN"
                   else EngineRun(temp, technique))
        with adapter:
            load, _ = timed(lambda: adapter.load(csv))
            build, _ = timed(adapter.build)
            if technique == "GIN":
                adapter.analyze()
            samples, rankings = query_trials(adapter, queries, relevant, size)
            # Memoria antes de EXPLAIN y antes de serializar los resultados.
            client = process_memory()
            memory = adapter.memory() if technique == "GIN" else client
            baseline = adapter.initial_memory if technique == "GIN" else initial
            result = {"load_seconds": load, "build_seconds": build, "ready_seconds": load + build,
                      **adapter.disk(), "rss_initial_bytes": baseline["VmRSS"],
                      "rss_peak_bytes": memory["VmHWM"], "client_peak_bytes": client["VmHWM"],
                      "memory_scope": "postgres_backend" if technique == "GIN" else "python_worker",
                      "samples": samples, "rankings": rankings}
            if technique == "GIN":
                result["server_version"] = adapter.version
                result["plans"] = {q["query_id"]: adapter.explain(q["text"]) for q in queries}
                result["settings"] = {key: adapter.connection.execute("SHOW " + key).fetchone()[0]
                                      for key in ("shared_buffers", "work_mem", "maintenance_work_mem", "max_parallel_workers_per_gather")}
            return result


if __name__ == "__main__":
    print(json.dumps(run(json.load(sys.stdin)), allow_nan=False))
