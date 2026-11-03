"""Archivos de resultados y resúmenes que conservan las repeticiones."""

import csv
import json
import statistics
from collections import defaultdict


def write_csv(path, rows):
    if not rows:
        raise ValueError("No hay mediciones para exportar")
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows({k: "NA" if v is None else v for k, v in row.items()} for row in rows)


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def summarize(rows, keys, metrics):
    groups = defaultdict(list)
    for row in rows:
        groups[tuple(row[key] for key in keys)].append(row)
    result = []
    for key, samples in sorted(groups.items()):
        out = dict(zip(keys, key))
        out["samples"] = len(samples)
        for metric in metrics:
            values = [row[metric] for row in samples if row[metric] is not None]
            out[metric] = statistics.fmean(values) if values else None
            out[metric + "_std"] = statistics.stdev(values) if len(values) > 1 else 0 if values else None
            out[metric + "_min"] = min(values) if values else None
            out[metric + "_max"] = max(values) if values else None
        result.append(out)
    return result
