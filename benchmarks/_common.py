"""Salida CSV/PNG, repeticiones y metadatos comunes; no ejecuta benchmarks al importar."""

import argparse
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import tempfile

RESULTS = Path(__file__).resolve().parent / "results"
OFFICIAL_SIZES = (1_000, 10_000, 100_000)
NA = "NA"


def arguments(description):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--sizes", type=int, nargs="+", default=list(OFFICIAL_SIZES))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--repetitions", type=int, default=3,
                        help="Corridas por tamaño; el CSV guarda media y desviación estándar")
    parser.add_argument("--output-dir", type=Path, default=RESULTS)
    args = parser.parse_args()
    if any(n < 200 for n in args.sizes) or len(set(args.sizes)) != len(args.sizes):
        parser.error("Los tamaños deben ser distintos y >= 200 (se consultan 100 claves existentes)")
    if args.repetitions < 1:
        parser.error("--repetitions debe ser >= 1")
    args.sizes.sort()
    return args


def summarize(runs, key_fields, metrics):
    """runs: filas de todas las repeticiones. Agrupa por key_fields.

    Para cada métrica numérica escribe <métrica> (media) y <métrica>_std.
    Las métricas NA se mantienen NA (operación no soportada o no medida).
    """
    groups = {}
    for row in runs:
        groups.setdefault(tuple(row[k] for k in key_fields), []).append(row)
    summary = []
    for key, rows in groups.items():
        out = dict(zip(key_fields, key))
        out["repeticiones"] = len(rows)
        for metric in metrics:
            values = [row[metric] for row in rows]
            if any(value == NA for value in values):
                out[metric], out[metric + "_std"] = NA, NA
            else:
                out[metric] = statistics.fmean(values)
                out[metric + "_std"] = statistics.stdev(values) if len(values) > 1 else 0.0
        summary.append(out)
    return summary


def write_csv(path, rows, fields):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def series(rows, technique, metric, label=None, scale=1.0):
    """(etiqueta, xs, ys, errores) de una técnica; omite NA."""
    data = [row for row in rows if row["tecnica"] == technique and row[metric] != NA]
    return (label or technique, [row["n_registros"] for row in data],
            [row[metric] * scale for row in data],
            [row.get(metric + "_std", 0.0) * scale for row in data])


def plot(path, title, ylabel, all_series, note=None):
    """Gráfica log-log con barras de error (desviación estándar)."""
    previous = os.environ.get("MPLCONFIGDIR")
    with tempfile.TemporaryDirectory(prefix="bd2-matplotlib-") as cache:
        if previous is None:
            os.environ["MPLCONFIGDIR"] = cache
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            fig, ax = plt.subplots(figsize=(9, 5.5))
            for label, xs, ys, errors in all_series:
                if xs:
                    ax.errorbar(xs, ys, yerr=errors, marker="o", capsize=4, label=label)
            ax.set(xscale="log", yscale="log", title=title,
                   xlabel="Registros (N, escala logarítmica)", ylabel=ylabel + " (escala logarítmica)")
            if note:
                ax.text(0.01, -0.16, note, transform=ax.transAxes, fontsize=8, color="0.35")
            ax.legend()
            ax.grid(True, which="both", alpha=0.3)
            fig.tight_layout()
            fig.savefig(path, dpi=160)
            plt.close(fig)
        finally:
            if previous is None:
                os.environ.pop("MPLCONFIGDIR", None)


def write_metadata(args, prefix, elapsed, details):
    import matplotlib
    metadata = {"timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "python": sys.version, "platform": platform.platform(), "machine": platform.machine(),
                "seed": args.seed, "sizes": args.sizes, "repetitions": args.repetitions,
                "elapsed_seconds": elapsed, "matplotlib": matplotlib.__version__, **details}
    with (args.output_dir / f"{prefix}_metadata.json").open("w", encoding="utf-8") as stream:
        json.dump(metadata, stream, indent=2, ensure_ascii=False)
        stream.write("\n")


def print_table(rows, fields):
    formatted = [[f"{r[f]:.6f}" if isinstance(r[f], float) else str(r[f]) for f in fields] for r in rows]
    widths = [max(len(f), *(len(row[i]) for row in formatted)) for i, f in enumerate(fields)]
    print(" | ".join(f.ljust(w) for f, w in zip(fields, widths)))
    print("-+-".join("-" * w for w in widths))
    for row in formatted:
        print(" | ".join(value.ljust(w) for value, w in zip(row, widths)))


def progress(message):
    print(message, file=sys.stderr, flush=True)
