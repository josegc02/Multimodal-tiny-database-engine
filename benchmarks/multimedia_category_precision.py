"""Precisión por categoría COCO de los diez vecinos que guardó multimedia_compare en queries.json.

Un vecino cuenta como acierto si su imagen contiene la categoría de la consulta (COCO es
multietiqueta). La línea base "azar" es la fracción de imágenes del subconjunto con esa categoría.
No reemplaza a Recall@10: mide relevancia semántica, que SIFT + BoVW no está diseñado para capturar.

    python -m benchmarks.multimedia_category_precision --dataset-dir datasets/coco_subsets \\
        --results benchmarks/results/smoke/multimedia
"""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path


def subset_categories(directory: Path):
    manifest = json.loads((directory / "instances_subset.json").read_text(encoding="utf-8"))
    names = {c["id"]: c["name"] for c in manifest["categories"]}
    files = {image["id"]: image["file_name"] for image in manifest["images"]}
    categories = defaultdict(set)
    for annotation in manifest["annotations"]:
        categories[files[annotation["image_id"]]].add(names[annotation["category_id"]])
    frequency = Counter(name for file in files.values() for name in categories[file])
    return categories, frequency, len(files)


def category_precision(dataset_dir: Path, rows: list[dict]) -> list[dict]:
    subsets = {}
    groups = defaultdict(list)
    for row in rows:
        size = row["size"]
        if size not in subsets:
            subsets[size] = subset_categories(dataset_dir / f"coco{size // 1000}k")
        categories, frequency, total = subsets[size]
        category = row["category"]
        key = (size, row["metric"])
        groups[key + (row["technique"],)].append(sum(category in categories[f] for f in row["found_files"]) / 10)
        if row["technique"] == "IVF":  # la referencia exacta y el azar se cuentan una vez por consulta
            groups[key + ("exacto",)].append(sum(category in categories[f] for f in row["exact_files"]) / 10)
            groups[key + ("azar",)].append(frequency[category] / total)
    return [{"size": size, "metric": metric, "technique": technique, "queries": len(values),
             "precision_at_10": sum(values) / len(values)}
            for (size, metric, technique), values in sorted(groups.items())]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset-dir", type=Path, default=Path("datasets/coco_subsets"))
    parser.add_argument("--results", type=Path, required=True, help="Salida de multimedia_compare")
    args = parser.parse_args(argv)
    rows = json.loads((args.results / "queries.json").read_text(encoding="utf-8"))
    result = category_precision(args.dataset_dir, rows)
    (args.results / "category_precision.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    for row in result:
        print(f'{row["size"]:>6} {row["metric"]:<9} {row["technique"]:<6} P@10={row["precision_at_10"]:.3f}')


if __name__ == "__main__":
    main()
