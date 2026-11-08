"""Gráficas del benchmark multimedia, generadas a partir de summary.csv."""

import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from benchmarks.multimedia_report import index_memory


MEASURES = (
    ("build_seconds", "Construcción (s)", "construction.png"),
    ("mean_query_seconds", "Consulta media (s)", "query.png"),
    ("mean_recall_at_10", "Recall@10 frente a vecinos exactos", "recall.png"),
    ("index_memory", "Memoria del índice: pico − inicial (MiB)", "memory.png"),
)


def plot_results(output: Path):
    with (output / "summary.csv").open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise ValueError("summary.csv está vacío")
    for field, label, filename in MEASURES:
        fig, axes = plt.subplots(1, 2, figsize=(11, 4), sharey=True)
        for ax, metric in zip(axes, ("euclidean", "cosine")):
            for technique in ("IVF", "HNSW"):
                subset = sorted((r for r in rows if r["metric"] == metric and
                                 r["technique"] == technique), key=lambda r: int(r["size"]))
                if subset:
                    values = [index_memory(r) / 1024 ** 2 if field == "index_memory" else float(r[field])
                              for r in subset]
                    ax.plot([int(r["size"]) for r in subset], values, marker="o", label=technique)
            ax.set_title(metric)
            ax.set_xscale("log")
            ax.set_xlabel("Imágenes indexadas")
            ax.grid(True, alpha=0.3)
            ax.legend()
        axes[0].set_ylabel(label)
        fig.tight_layout()
        fig.savefig(output / filename, dpi=150)
        plt.close(fig)
