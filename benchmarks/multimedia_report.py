"""Tabla y conclusiones derivadas únicamente de las mediciones ejecutadas."""

import csv
import json
from pathlib import Path


def vector_dimension(output: Path, features: str) -> int | None:
    """Dimensión de los vectores medidos, leída de la caché que dejó el benchmark."""
    import numpy as np

    for cache in sorted(output.glob(f"vectors_{features}_*.npz")):
        with np.load(cache, allow_pickle=False) as saved:
            return int(saved["vectors"].shape[1])
    return None


def index_memory(row: dict) -> int:
    """Memoria atribuible al índice: pico del proceso menos la memoria antes de construirlo."""
    return max(0, int(row["rss_peak_bytes"]) - int(row["rss_initial_bytes"]))


def write_report(output: Path):
    with (output / "summary.csv").open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise ValueError("No hay mediciones")
    features_path = output / "features.json"
    features = (json.loads(features_path.read_text(encoding="utf-8"))["features"]
                if features_path.is_file() else "sift-mean")
    if features == "bovw":
        dimension = vector_dimension(output, features)
        size = f"K={dimension}, " if dimension else ""
        description = (f"Los vectores son histogramas Bag of Visual Words ({size}TF-IDF) de los puntos SIFT "
                       "de imágenes COCO. Tienen norma L2 igual a 1, así que ‖a − b‖² = 2 − 2·cos(a, b): "
                       "la distancia euclidiana y el coseno ordenan los vecinos exactos igual. Las diferencias "
                       "entre métricas vienen de cada índice: IVF agrupa con k-means euclidiano o esférico "
                       "(coseno) y HNSW arma un grafo distinto según la métrica.")
    else:
        description = "Los vectores son promedios SIFT de imágenes COCO."
    lines = ["# Comparación experimental multimedia (#59)", "",
             description + " Cada configuración usa el mismo corpus y "
             "las mismas consultas; el vector de la consulta se excluye de los resultados. "
             "Recall@10 compara los diez IDs recuperados con los diez vecinos exactos bajo la misma métrica. "
             "No mide relevancia semántica por categoría.", "",
             "| Imágenes | Métrica | Índice | Construcción (s) | Consulta media (ms) | Recall@10 | Pico RSS (MiB) "
             "| Memoria del índice (MiB) |",
             "|---:|---|---|---:|---:|---:|---:|---:|"]
    counts_path = output / "fallback_counts.json"
    if counts_path.is_file():
        counts = json.loads(counts_path.read_text(encoding="utf-8"))
        details = ", ".join(f"{size}: {count}" for size, count in counts.items())
        if features == "bovw":
            lines[2] += (" Las imágenes sin puntos SIFT tienen el vector nulo: se excluyen de las corridas "
                         f"con coseno; casos por tamaño: {details}.")
        else:
            lines[2] += (" Las imágenes sin puntos SIFT usan un histograma gris de 128 dimensiones "
                         f"escalado al tamaño mediano de los vectores SIFT; casos por tamaño: {details}.")
    for row in sorted(rows, key=lambda r: (int(r["size"]), r["metric"], r["technique"])):
        lines.append(f'| {row["size"]} | {row["metric"]} | {row["technique"]} | '
                     f'{float(row["build_seconds"]):.3f} | '
                     f'{float(row["mean_query_seconds"]) * 1000:.3f} | '
                     f'{float(row["mean_recall_at_10"]):.3f} | '
                     f'{int(row["rss_peak_bytes"]) / 1024 ** 2:.1f} | '
                     f'{index_memory(row) / 1024 ** 2:.1f} |')
    lines.extend(["", "## Recomendaciones basadas en estas corridas", ""])
    for size in sorted({int(r["size"]) for r in rows}):
        for metric in ("euclidean", "cosine"):
            group = [r for r in rows if int(r["size"]) == size and r["metric"] == metric]
            if len(group) != 2:
                continue
            fast = min(group, key=lambda r: float(r["mean_query_seconds"]))
            accurate = max(group, key=lambda r: float(r["mean_recall_at_10"]))
            low_memory = min(group, key=index_memory)
            lines.append(f'- {size} imágenes, {metric}: **{fast["technique"]}** tuvo menor latencia media; '
                         f'**{accurate["technique"]}** obtuvo mayor Recall@10; '
                         f'**{low_memory["technique"]}** usó menos memoria para el índice.')
    lines.extend(["", "Estos resultados corresponden a una sola corrida por configuración, "
                  "sin intervalos de confianza. El pico RSS incluye el intérprete, los vectores cargados y las "
                  "páginas compartidas. La memoria del índice es el pico menos la memoria del proceso justo antes "
                  "de construirlo (vectores ya cargados): aproxima lo que ocupa el índice y su construcción, "
                  "igual para IVF y HNSW. Para comparar máquinas o tomar decisiones "
                  "de producción hay que repetir las corridas bajo condiciones controladas.", "",
                  "![Construcción](construction.png)", "![Consultas](query.png)",
                  "![Recall](recall.png)", "![Memoria](memory.png)", "",
                  "[Galería de casos](gallery.html)", ""])
    (output / "report.md").write_text("\n".join(lines), encoding="utf-8")
