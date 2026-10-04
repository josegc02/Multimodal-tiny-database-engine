"""Compara la complejidad teórica con la medida (pendiente en escala log-log).

python benchmarks/complexity.py [--results benchmarks/results]

Para cada curva calcula la pendiente entre tamaños consecutivos:
    pendiente = log(t2 / t1) / log(N2 / N1)
Un costo constante o logarítmico da una pendiente cercana a 0; uno lineal,
cercana a 1. Imprime una tabla en markdown con el veredicto de cada curva.

El veredicto usa el último tramo (los dos tamaños mayores): la complejidad es
asintótica y con N pequeño pesan costos fijos (abrir archivos, fsync, cachés
frías). Las dos pendientes se muestran igual en la tabla.
"""

import argparse
import csv
import math
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmarks._common import RESULTS

# Rango de pendientes compatibles con cada complejidad (por operación o total).
EXPECTED = {
    "O(1)": (-0.35, 0.35),
    "O(log N)": (-0.35, 0.35),
    "O(log N + k)": (-0.35, 0.35),
    "O(N)": (0.65, 1.35),
    "O(N log N)": (0.85, 1.5),
}

# (archivo, técnica, métrica, divisor, descripción, complejidad esperada)
# divisor: "n" = por registro, número = cantidad de operaciones, None = total.
CURVES = [
    ("storage", "HeapFile", "tiempo_insercion_seg", "n", "Inserción (por registro)", "O(1)"),
    ("storage", "SequentialFile", "tiempo_insercion_seg", "n", "Inserción (por registro)", "O(log N)"),
    ("storage", "HeapFile", "tiempo_busqueda_seg", 100, "Búsqueda por PK (por consulta)", "O(N)"),
    ("storage", "SequentialFile", "tiempo_busqueda_seg", 100, "Búsqueda por PK tras la carga", "O(log N)"),
    ("storage", "SequentialFile", "tiempo_busqueda_post_reorg_seg", 100, "Búsqueda por PK tras reorganizar", "O(log N)"),
    ("storage", "HeapFile", "espacio_disco_bytes", None, "Espacio en disco", "O(N)"),
    ("storage", "SequentialFile", "espacio_disco_bytes", None, "Espacio en disco", "O(N)"),
    ("storage", "SequentialFile", "tiempo_reorganizacion_seg", None, "Reorganización", "O(N)"),
    ("indexes", "B+ agrupado", "tiempo_construccion_seg", "n", "Construcción (por inserción)", "O(log N)"),
    ("indexes", "B+ no agrupado", "tiempo_construccion_seg", "n", "Construcción (por inserción)", "O(log N)"),
    ("indexes", "Extendible Hash", "tiempo_construccion_seg", "n", "Construcción (por inserción)", "O(1)"),
    ("indexes", "Extendible Hash", "tiempo_snapshot_seg", None, "Snapshot JSON del hash", "O(N)"),
    ("indexes", "B+ agrupado", "tiempo_igualdad_seg", 100, "Igualdad (por consulta)", "O(log N)"),
    ("indexes", "B+ no agrupado", "tiempo_igualdad_seg", 100, "Igualdad (por consulta)", "O(log N)"),
    ("indexes", "Extendible Hash", "tiempo_igualdad_seg", 100, "Igualdad (por consulta)", "O(1)"),
    ("indexes", "B+ agrupado", "tiempo_rango_seg", 20, "Rango de 101 claves (por consulta)", "O(log N + k)"),
    ("indexes", "B+ no agrupado", "tiempo_rango_seg", 20, "Rango de 101 claves (por consulta)", "O(log N + k)"),
    ("indexes", "B+ agrupado", "tiempo_orden_seg", None, "ORDER BY tabla completa", "O(N)"),
    ("indexes", "B+ no agrupado", "tiempo_orden_seg", None, "ORDER BY tabla completa", "O(N)"),
    ("indexes", "Extendible Hash", "tiempo_orden_seg", None, "ORDER BY (scan + external sort)", "O(N log N)"),
    ("indexes", "B+ agrupado", "espacio_adicional_bytes", None, "Espacio adicional", "O(N)"),
    ("indexes", "B+ no agrupado", "espacio_adicional_bytes", None, "Espacio adicional", "O(N)"),
    ("indexes", "Extendible Hash", "espacio_adicional_bytes", None, "Espacio adicional", "O(N)"),
    ("indexes", "B+ agrupado", "tiempo_actualizaciones_seg", 1000, "Inserción/eliminación (por operación)", "O(log N)"),
    ("indexes", "B+ no agrupado", "tiempo_actualizaciones_seg", 1000, "Inserción/eliminación (por operación)", "O(log N)"),
    ("indexes", "Extendible Hash", "tiempo_actualizaciones_seg", 1000, "Inserción/eliminación (por operación)", "O(1)"),
]


def load(path):
    data = {}
    with open(path, encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            data.setdefault(row["tecnica"], {})[int(row["n_registros"])] = row
    return data


def slopes(points):
    return [math.log10(points[i + 1][1] / points[i][1]) / math.log10(points[i + 1][0] / points[i][0])
            for i in range(len(points) - 1)]


def table(results: Path):
    files = {"storage": load(results / "storage_comparison.csv"),
             "indexes": load(results / "indexes_comparison.csv")}
    lines = ["| Estructura | Medición | Teoría | Pendiente 1K→10K / 10K→100K | ¿Coincide? |",
             "| :--- | :--- | :---: | :---: | :---: |"]
    ok = True
    for source, technique, metric, per, label, expected in CURVES:
        rows = files[source].get(technique, {})
        points = []
        for n, row in sorted(rows.items()):
            if row[metric] in ("NA", ""):
                continue
            value = float(row[metric])
            value /= n if per == "n" else (per or 1)
            points.append((n, value))
        if len(points) < 2:
            continue
        measured = slopes(points)
        low, high = EXPECTED[expected]
        match = low <= measured[-1] <= high
        ok &= match
        text = " / ".join(f"{s:+.2f}".replace(".", ",") for s in measured)
        lines.append(f"| {technique} | {label} | {expected} | {text} | {'Sí' if match else 'No'} |")
    return "\n".join(lines), ok


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--results", type=Path, default=RESULTS)
    args = parser.parse_args()
    text, ok = table(args.results)
    print(text)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
