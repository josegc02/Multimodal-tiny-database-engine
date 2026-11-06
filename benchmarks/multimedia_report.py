"""Tabla y conclusiones derivadas únicamente de las mediciones ejecutadas."""

import csv
import json
from pathlib import Path


def write_report(output: Path):
    with (output / "summary.csv").open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise ValueError("No hay mediciones")
    lines = ["# Comparación experimental multimedia (#59)", "",
             "Los vectores son promedios SIFT de imágenes COCO. Cada configuración usa el mismo corpus y "
             "las mismas consultas; el vector de la consulta se excluye de los resultados. "
             "Recall@10 compara los diez IDs recuperados con los diez vecinos exactos bajo la misma métrica. "
             "No mide relevancia semántica por categoría.", "",
             "| Imágenes | Métrica | Índice | Construcción (s) | Consulta media (ms) | Recall@10 | Pico RSS (MiB) |",
             "|---:|---|---|---:|---:|---:|---:|"]
    counts_path = output / "fallback_counts.json"
    if counts_path.is_file():
        counts = json.loads(counts_path.read_text(encoding="utf-8"))
        details = ", ".join(f"{size}: {count}" for size, count in counts.items())
        lines[2] += (" Las imágenes sin puntos SIFT usan un histograma gris de 128 dimensiones "
                     f"escalado al tamaño mediano de los vectores SIFT; casos por tamaño: {details}.")
    for row in sorted(rows, key=lambda r: (int(r["size"]), r["metric"], r["technique"])):
        lines.append(f'| {row["size"]} | {row["metric"]} | {row["technique"]} | '
                     f'{float(row["build_seconds"]):.3f} | '
                     f'{float(row["mean_query_seconds"]) * 1000:.3f} | '
                     f'{float(row["mean_recall_at_10"]):.3f} | '
                     f'{int(row["rss_peak_bytes"]) / 1024 ** 2:.1f} |')
    lines.extend(["", "## Recomendaciones basadas en estas corridas", ""])
    for size in sorted({int(r["size"]) for r in rows}):
        for metric in ("euclidean", "cosine"):
            group = [r for r in rows if int(r["size"]) == size and r["metric"] == metric]
            if len(group) != 2:
                continue
            fast = min(group, key=lambda r: float(r["mean_query_seconds"]))
            accurate = max(group, key=lambda r: float(r["mean_recall_at_10"]))
            low_memory = min(group, key=lambda r: int(r["rss_peak_bytes"]))
            lines.append(f'- {size} imágenes, {metric}: **{fast["technique"]}** tuvo menor latencia media; '
                         f'**{accurate["technique"]}** obtuvo mayor Recall@10; '
                         f'**{low_memory["technique"]}** registró menor pico RSS.')
    lines.extend(["", "Estos resultados corresponden a una sola corrida por configuración, "
                  "sin intervalos de confianza. El pico RSS incluye el intérprete y las páginas compartidas; "
                  "no representa la memoria exclusiva del índice. Para comparar máquinas o tomar decisiones "
                  "de producción hay que repetir las corridas bajo condiciones controladas.", "",
                  "![Construcción](construction.png)", "![Consultas](query.png)",
                  "![Recall](recall.png)", "![Memoria](memory.png)", "",
                  "[Galería de casos](gallery.html)", ""])
    (output / "report.md").write_text("\n".join(lines), encoding="utf-8")
