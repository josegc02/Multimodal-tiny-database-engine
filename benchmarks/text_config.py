"""Argumentos y validaciones del experimento, sin efectos al importar."""

import argparse
import os
from pathlib import Path

from postgres_text.client import DEFAULT_DSN


def arguments(argv=None):
    parser = argparse.ArgumentParser(description="Comparación textual TF-IDF, BM25 y GIN (#51)")
    parser.add_argument("--dataset-dir", type=Path, default=Path("datasets/text/generated"))
    parser.add_argument("--output", type=Path, default=Path("benchmarks/results/text"))
    parser.add_argument("--sizes", type=int, nargs="+", default=[1000, 10000, 100000])
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--dsn", default=os.environ.get("TEXT_POSTGRES_DSN", DEFAULT_DSN))
    parser.add_argument("--container", default="bd2-texto-postgres-1")
    parser.add_argument("--sin-postgres", action="store_true", help="Corrida parcial explícita, no cumple la comparación de tres técnicas")
    args = parser.parse_args(argv)
    if args.repetitions < 1 or any(n < 1 for n in args.sizes) or len(set(args.sizes)) != len(args.sizes):
        parser.error("Tamaños positivos distintos y repeticiones >= 1")
    args.sizes.sort()
    return args
