"""Salida CSV/PNG y metadatos comunes; no ejecuta benchmarks al importar."""

import argparse
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import sys
import tempfile
import time

RESULTS = Path(__file__).resolve().parent / "results"
OFFICIAL_SIZES = (1_000, 10_000, 100_000)


def arguments(description):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--sizes", type=int, nargs="+", default=list(OFFICIAL_SIZES))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output-dir", type=Path, default=RESULTS)
    args = parser.parse_args()
    if any(n < 100 for n in args.sizes) or len(set(args.sizes)) != len(args.sizes):
        parser.error("Los tamaños deben ser distintos y >= 100 (se consultan 100 claves existentes)")
    args.sizes.sort()
    return args


def save_results(rows, fields, plots, args, prefix, started, details):
    """plots: (columna, sufijo, título, unidad). NA se omite explícitamente."""
    os.makedirs(args.output_dir, exist_ok=True)
    csv_path = args.output_dir / f"{prefix}_comparison.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    # Backend sin interfaz gráfica, caché escribible y eliminada al terminar.
    previous = os.environ.get("MPLCONFIGDIR")
    with tempfile.TemporaryDirectory(prefix="bd2-matplotlib-") as cache:
        if previous is None:
            os.environ["MPLCONFIGDIR"] = cache
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            for column, suffix, title, unit in plots:
                fig, ax = plt.subplots(figsize=(9, 5.5))
                for technique in dict.fromkeys(row["tecnica"] for row in rows):
                    data = [row for row in rows if row["tecnica"] == technique
                            and isinstance(row[column], (int, float))]
                    if data:
                        ax.plot([row["n_registros"] for row in data], [row[column] for row in data],
                                marker="o", label=technique)
                ax.set(xscale="log", xlabel="Registros (N, escala logarítmica)", ylabel=unit, title=title)
                if "seg" in column:
                    ax.set_yscale("log")
                    ax.set_ylabel(unit + " (escala logarítmica)")
                ax.legend()
                ax.grid(True, alpha=0.3)
                fig.tight_layout()
                fig.savefig(args.output_dir / f"{prefix}_{suffix}.png", dpi=160)
                plt.close(fig)
        finally:
            if previous is None:
                os.environ.pop("MPLCONFIGDIR", None)

    elapsed = time.perf_counter() - started
    metadata = {"timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "python": sys.version, "platform": platform.platform(), "machine": platform.machine(),
                "seed": args.seed, "sizes": args.sizes, "repetitions": 1,
                "elapsed_seconds": elapsed, "matplotlib": matplotlib.__version__, **details}
    with (args.output_dir / f"{prefix}_metadata.json").open("w", encoding="utf-8") as stream:
        json.dump(metadata, stream, indent=2, ensure_ascii=False)
        stream.write("\n")

    formatted = [[f"{r[f]:.6f}" if isinstance(r[f], float) else str(r[f]) for f in fields] for r in rows]
    widths = [max(len(f), *(len(row[i]) for row in formatted)) for i, f in enumerate(fields)]
    print(" | ".join(f.ljust(w) for f, w in zip(fields, widths)))
    print("-+-".join("-" * w for w in widths))
    for row in formatted:
        print(" | ".join(value.ljust(w) for value, w in zip(row, widths)))
    print(f"\nResultados: {args.output_dir.resolve()}\nDuración completa: {elapsed:.3f} s")
    return elapsed
