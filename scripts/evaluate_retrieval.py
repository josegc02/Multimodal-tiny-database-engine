"""
Script para evaluar la recuperación de imágenes usando SIFT + HNSW.

Extrae descriptores SIFT de las imágenes de un subset de COCO,
las indexa en HNSW, ejecuta las queries y calcula Recall@10.

Uso:
    python scripts/evaluate_retrieval.py --subset coco1k
    python scripts/evaluate_retrieval.py --subset coco10k --ef-search 100
"""

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

# Ajusta estas rutas según tu estructura
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine.features.image import SIFTExtractor
from engine.indexes.hnsw import HNSWIndex


DATASETS_DIR = PROJECT_ROOT / "datasets" / "coco_subsets"
IMAGES_DIR_NAME = "images"
QUERIES_FILE = "queries.json"


def load_queries(subset_dir: Path) -> dict:
    """Carga el archivo queries.json del subset."""
    queries_path = subset_dir / QUERIES_FILE
    if not queries_path.exists():
        print(f"Error: no se encontro {queries_path}", file=sys.stderr)
        print("Ejecuta primero: python scripts/generate_queries.py", file=sys.stderr)
        sys.exit(1)
    with open(queries_path, "r") as f:
        return json.load(f)


def list_images(subset_dir: Path) -> list[str]:
    """Lista los nombres de archivo de todas las imágenes del subset."""
    images_dir = subset_dir / IMAGES_DIR_NAME
    if not images_dir.exists():
        print(f"Error: no se encontro {images_dir}", file=sys.stderr)
        sys.exit(1)
    return sorted(
        f.name for f in images_dir.iterdir()
        if f.suffix.lower() in (".jpg", ".jpeg", ".png")
    )


def extract_and_index(
    image_files: list[str],
    subset_dir: Path,
    extractor: SIFTExtractor,
    index: HNSWIndex,
) -> dict[str, int]:
    """
    Extrae SIFT de cada imagen y la inserta en el índice HNSW.
    Retorna un mapeo file_name -> identifier.
    """
    file_to_id: dict[str, int] = {}
    failed = 0
    images_dir = subset_dir / IMAGES_DIR_NAME

    for idx, filename in enumerate(image_files, start=1):
        img_path = images_dir / filename
        try:
            vector = extractor.extract_to_fixed_vector(str(img_path), method="average")
            index.insert(idx, vector.tolist())
            file_to_id[filename] = idx
        except Exception as e:
            failed += 1
            if failed <= 5:
                print(f"  Falla en {filename}: {e}")

    if failed > 0:
        print(f"  {failed} imagenes fallaron al extraer SIFT")

    return file_to_id


def evaluate_query(
    query: dict,
    subset_dir: Path,
    extractor: SIFTExtractor,
    index: HNSWIndex,
    file_to_id: dict[str, int],
    k: int,
    ef_search: int,
) -> dict:
    """
    Ejecuta una query y retorna métricas de recuperación.
    """
    query_file = query["query_file"]
    relevant_files = set(query["relevant_files"])
    query_path = subset_dir / IMAGES_DIR_NAME / query_file

    try:
        query_vector = extractor.extract_to_fixed_vector(str(query_path), method="average")
    except Exception as e:
        return {
            "query_file": query_file,
            "category": query["category_name"],
            "error": str(e),
            "recall": 0.0,
        }

    result = index.search(query_vector.tolist(), k=k, ef_search=ef_search)

    retrieved_ids = {match[0] for match in result.matches}
    id_to_file = {v: k for k, v in file_to_id.items()}
    retrieved_files = {id_to_file[i] for i in retrieved_ids if i in id_to_file}

    retrieved_files.discard(query_file)
    relevant_retrieved = relevant_files & retrieved_files
    total_relevant = len(relevant_files)

    recall = len(relevant_retrieved) / total_relevant if total_relevant > 0 else 0.0

    return {
        "query_file": query_file,
        "category": query["category_name"],
        "total_relevant": total_relevant,
        "retrieved_in_top_k": len(relevant_retrieved),
        "recall": recall,
        "nodes_visited": result.nodes_visited,
    }


def run_evaluation(
    subset_name: str,
    k: int = 10,
    ef_search: int = 50,
    output_csv: str | None = None,
) -> None:
    """Ejecuta la evaluación completa para un subset."""
    subset_dir = DATASETS_DIR / subset_name
    if not subset_dir.exists():
        print(f"Error: no se encontro el subset {subset_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Evaluando {subset_name}...")

    queries_data = load_queries(subset_dir)
    image_files = list_images(subset_dir)
    print(f"  {len(image_files)} imagenes, {queries_data['total_queries']} queries")

    extractor = SIFTExtractor(n_features=500)
    index = HNSWIndex(M=8, ef_construction=50, metric="euclidean")

    print("  Extrayendo SIFT e indexando...")
    t0 = time.time()
    file_to_id = extract_and_index(image_files, subset_dir, extractor, index)
    t_index = time.time() - t0
    print(f"  Indexacion completada en {t_index:.1f}s")

    print("  Ejecutando queries...")
    t0 = time.time()
    results = []
    for q in queries_data["queries"]:
        r = evaluate_query(q, subset_dir, extractor, index, file_to_id, k, ef_search)
        results.append(r)
    t_search = time.time() - t0
    print(f"  Busqueda completada en {t_search:.1f}s")

    recalls = [r["recall"] for r in results if "error" not in r]
    avg_recall = sum(recalls) / len(recalls) if recalls else 0.0
    print(f"  Recall@{k}: {avg_recall:.4f} ({avg_recall * 100:.1f}%)")

    if output_csv:
        output_path = Path(output_csv)
    else:
        output_path = subset_dir / f"results_recall{k}.csv"

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["query_file", "category", "total_relevant",
                        "retrieved_in_top_k", "recall", "nodes_visited", "error"],
        )
        writer.writeheader()
        writer.writerows(results)

    print(f"  Resultados guardados en: {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluar retrieval con SIFT + HNSW")
    parser.add_argument("--subset", type=str, help="Subset a evaluar (coco1k, coco10k, coco100k)")
    parser.add_argument("--k", type=int, default=10, help="Numero de vecinos a recuperar")
    parser.add_argument("--ef-search", type=int, default=50, help="Parametro ef_search de HNSW")
    parser.add_argument("--output", type=str, help="Ruta del CSV de salida")
    args = parser.parse_args()

    if args.subset:
        run_evaluation(args.subset, args.k, args.ef_search, args.output)
    else:
        for subset in ["coco1k", "coco10k", "coco100k"]:
            run_evaluation(subset, args.k, args.ef_search, args.output)

    print("\nEvaluacion completada.")


if __name__ == "__main__":
    main()