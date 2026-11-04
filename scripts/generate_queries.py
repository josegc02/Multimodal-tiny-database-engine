"""
Script para generar queries de prueba y su ground truth a partir de los subsets de COCO.

Para cada categoría presente en el subset, selecciona una imagen como query
y el resto de imágenes de esa categoría como ground truth (relevantes).

Uso:
    python scripts/generate_queries.py
    python scripts/generate_queries.py --subset coco1k --max-queries 20
"""

import argparse
import json
import os
import random
import sys
from collections import defaultdict

DATASETS_DIR = "datasets/coco_subsets"
RANDOM_SEED = 42


def load_subset(subset_name: str) -> dict:
    """Carga el archivo de anotaciones de un subset."""
    annotations_path = os.path.join(DATASETS_DIR, subset_name, "instances_subset.json")
    if not os.path.exists(annotations_path):
        print(f"Error: no se encontro {annotations_path}", file=sys.stderr)
        print("Ejecuta primero: python scripts/create_subsets.py", file=sys.stderr)
        sys.exit(1)
    
    with open(annotations_path, "r") as f:
        return json.load(f)


def group_images_by_category(data: dict) -> dict:
    """Agrupa las imágenes por categoría."""
    img_to_categories = defaultdict(set)
    for ann in data["annotations"]:
        img_to_categories[ann["image_id"]].add(ann["category_id"])
    
    cat_to_images = defaultdict(list)
    for img in data["images"]:
        img_id = img["id"]
        cats = img_to_categories.get(img_id, set())
        if len(cats) == 1:
            cat_id = list(cats)[0]
            cat_to_images[cat_id].append(img)
    
    return cat_to_images


def build_category_map(data: dict) -> dict:
    """Crea un mapeo de category_id a category_name."""
    return {cat["id"]: cat["name"] for cat in data["categories"]}


def generate_queries(
    cat_to_images: dict,
    category_map: dict,
    max_queries: int = None
) -> list:
    """Genera las queries seleccionando una imagen por categoría."""
    random.seed(RANDOM_SEED)
    
    queries = []
    categories = sorted(cat_to_images.keys())
    
    if max_queries:
        categories = random.sample(categories, min(max_queries, len(categories)))
    
    for cat_id in categories:
        images = cat_to_images[cat_id]
        if len(images) < 2:
            continue
        
        query_img = random.choice(images)
        relevant_imgs = [img for img in images if img["id"] != query_img["id"]]
        
        queries.append({
            "query_id": query_img["id"],
            "query_file": query_img["file_name"],
            "category_id": cat_id,
            "category_name": category_map.get(cat_id, "unknown"),
            "total_relevant": len(relevant_imgs),
            "relevant_files": [img["file_name"] for img in relevant_imgs]
        })
    
    return queries


def save_queries(queries: list, subset_name: str, total_images: int) -> str:
    """Guarda las queries en un archivo JSON."""
    output = {
        "subset": subset_name,
        "total_images": total_images,
        "total_queries": len(queries),
        "queries": queries
    }
    
    output_path = os.path.join(DATASETS_DIR, subset_name, "queries.json")
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)
    
    return output_path


def process_subset(subset_name: str, max_queries: int = None) -> None:
    """Procesa un subset y genera sus queries."""
    print(f"Procesando {subset_name}...")
    
    data = load_subset(subset_name)
    cat_to_images = group_images_by_category(data)
    category_map = build_category_map(data)
    queries = generate_queries(cat_to_images, category_map, max_queries)
    
    if not queries:
        print(f"  No se pudieron generar queries para {subset_name}")
        return
    
    output_path = save_queries(queries, subset_name, len(data["images"]))
    print(f"  {len(queries)} queries generadas")
    print(f"  Guardado en: {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generar queries y ground truth para COCO")
    parser.add_argument("--subset", type=str, help="Nombre del subset (coco1k, coco10k, coco100k)")
    parser.add_argument("--max-queries", type=int, help="Numero maximo de queries por subset")
    args = parser.parse_args()
    
    if args.subset:
        process_subset(args.subset, args.max_queries)
    else:
        for subset in ["coco1k", "coco10k", "coco100k"]:
            process_subset(subset, args.max_queries)
    
    print("\nGeneracion de queries completada.")


if __name__ == "__main__":
    main()