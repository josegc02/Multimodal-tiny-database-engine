"""Proveniencia de resultados; nunca serializa credenciales de conexión."""

import importlib.metadata
import platform
import subprocess
from datetime import datetime, timezone


def environment(args, corpus):
    versions = {}
    for package in ("snowballstemmer", "psycopg", "matplotlib"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    dirty = subprocess.run(["git", "diff", "--quiet", "HEAD"]).returncode != 0
    return {"started_utc": datetime.now(timezone.utc).isoformat(), "git_revision": revision,
            "tracked_dirty": dirty, "python": platform.python_version(), "platform": platform.platform(),
            "packages": versions, "sizes": args.sizes, "repetitions": args.repetitions,
            "seed": args.seed, "top_k": 10, "bm25": {"k1": 1.2, "b": 0.75},
            "postgres_rank_normalization": 0, "warmup_passes": 1,
            "partial": args.sin_postgres, "corpus": corpus,
            "memory": "Linux VmHWM: fresh Python worker or fresh PostgreSQL backend, shared pages included",
            "postgres_storage": "temporary session tables; no WAL durability; serial query execution",
            "complete": False}
