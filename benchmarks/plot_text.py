"""Redibujar resultados sin repetir el experimento: python -m benchmarks.plot_text DIR."""

import argparse
import csv
import os
import tempfile
from pathlib import Path

COLORS = {"TF-IDF": "#2563eb", "BM25": "#d97706", "GIN": "#059669"}


def read_rows(path):
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        for key, value in row.items():
            if key != "technique":
                row[key] = None if value == "NA" else float(value)
    return rows


def curve(ax, rows, metric, scale=1, logarithmic=True):
    for technique, color in COLORS.items():
        values = sorted((row for row in rows if row["technique"] == technique and row[metric] is not None), key=lambda row: row["size"])
        if not values:
            continue
        xs = [row["size"] for row in values]
        ys = [row[metric] * scale for row in values]
        errors = [[(row[metric] - row[metric + "_min"]) * scale for row in values],
                  [(row[metric + "_max"] - row[metric]) * scale for row in values]]
        ax.errorbar(xs, ys, yerr=errors, label=technique, color=color, marker="o", capsize=4)
    sizes = sorted({row["size"] for row in rows})
    ax.set_xscale("log")
    if logarithmic:
        ax.set_yscale("log")
    ax.set_xticks(sizes, [f"{size:,.0f}" for size in sizes])
    ax.set_xlabel("Documentos")
    ax.grid(True, alpha=0.25)
    ax.legend()


def plot(directory):
    previous = os.environ.get("MPLCONFIGDIR")
    with tempfile.TemporaryDirectory(prefix="bd2-text-plots-") as cache:
        if previous is None:
            os.environ["MPLCONFIGDIR"] = cache
        try:
            _plot(directory)
        finally:
            if previous is None:
                os.environ.pop("MPLCONFIGDIR", None)


def _plot(directory):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    directory = Path(directory)
    builds = read_rows(directory / "build_summary.csv")
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), constrained_layout=True)
    for ax, metric, title in zip(axes, ("build_seconds", "ready_seconds"),
                                  ("Construcción del índice", "Carga + construcción")):
        curve(ax, builds, metric)
        ax.set_title(title)
        ax.set_ylabel("Segundos (escala log)")
    fig.suptitle("Texto: media y rango entre repeticiones")
    fig.savefig(directory / "construction.png", dpi=160)
    plt.close(fig)

    queries = read_rows(directory / "query_summary.csv")
    fig, axes = plt.subplots(1, 3, figsize=(14, 4), constrained_layout=True)
    for ax, words in zip(axes, (1, 3, 6)):
        curve(ax, [row for row in queries if row["words"] == words], "query_seconds", 1000)
        ax.set_title(f"{words} palabra(s)")
        ax.set_ylabel("Milisegundos por consulta (log)")
    fig.suptitle("Consultas calientes top-10: media y rango entre repeticiones")
    fig.savefig(directory / "query_latency.png", dpi=160)
    plt.close(fig)

    for metric, title in (("precision", "Precision@10"), ("recall", "Recall@10")):
        fig, axes = plt.subplots(1, 3, figsize=(14, 4), constrained_layout=True)
        for ax, words in zip(axes, (1, 3, 6)):
            curve(ax, [row for row in queries if row["words"] == words], metric, logarithmic=False)
            ax.set_title(f"{words} palabra(s)")
            ax.set_ylabel(title)
            ax.set_ylim(bottom=0, top=1.03 if metric == "precision" else None)
        fig.suptitle(f"{title}: juicios temáticos sintéticos, promedio macro por consulta")
        fig.savefig(directory / f"{metric}.png", dpi=160)
        plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(11, 4), constrained_layout=True)
    for ax, metric, title in zip(axes, ("index_bytes", "total_bytes"),
                                  ("Índice de búsqueda", "Datos + índices persistentes")):
        curve(ax, builds, metric, 1 / 2**20)
        ax.set_title(title)
        ax.set_ylabel("MiB (escala log)")
    fig.suptitle("Espacio en disco: sin CSV, WAL ni temporales de construcción")
    fig.savefig(directory / "disk.png", dpi=160)
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(11, 4), constrained_layout=True)
    for ax, metric, title in zip(axes, ("rss_initial_bytes", "rss_peak_bytes"),
                                  ("RSS al comenzar", "Pico RSS de la corrida")):
        curve(ax, builds, metric, 1 / 2**20, logarithmic=False)
        ax.set_title(title)
        ax.set_ylabel("MiB residentes")
    fig.suptitle("Python worker / backend PostgreSQL; incluye memoria compartida")
    fig.savefig(directory / "memory.png", dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    plot(parser.parse_args().directory)
