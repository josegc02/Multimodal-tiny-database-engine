"""Tablas Markdown reproducibles a partir de las mediciones agregadas."""

import argparse
from pathlib import Path

from benchmarks.plot_text import read_rows


def report(directory):
    directory = Path(directory)
    builds = read_rows(directory / "build_summary.csv")
    queries = read_rows(directory / "query_summary.csv")
    lines = ["# Resultados de texto", "", "Medias de repeticiones; datos completos en los CSV.", "",
             "| N | Técnica | Carga (s) | Índice (s) | Preparación (s) | Índice (MiB) | Total (MiB) | Pico RSS (MiB) |",
             "|---:|---|---:|---:|---:|---:|---:|---:|"]
    for row in builds:
        values = [row[m] for m in ("load_seconds", "build_seconds", "ready_seconds")]
        values += [row[m] / 2**20 for m in ("index_bytes", "total_bytes", "rss_peak_bytes")]
        lines.append(f"| {row['size']:.0f} | {row['technique']} | " + " | ".join(f"{v:.3f}" for v in values) + " |")
    lines += ["", "RSS: proceso Python o backend PostgreSQL, con páginas compartidas; no es memoria exclusiva del índice.", "",
              "| N | Técnica | Palabras | Consulta (ms) | Precision@10 | Recall@10 |",
              "|---:|---|---:|---:|---:|---:|"]
    for row in queries:
        recall = "NA" if row["recall"] is None else f"{row['recall']:.6f}"
        lines.append(f"| {row['size']:.0f} | {row['technique']} | {row['words']:.0f} | "
                     f"{row['query_seconds'] * 1000:.3f} | {row['precision']:.4f} | {recall} |")
    (directory / "tables.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    report(parser.parse_args().directory)
