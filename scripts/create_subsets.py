"""
Script para crear subsets de 1K, 10K y 100K del dataset MS-COCO 2017.

Lee las imagenes y anotaciones del dataset original y crea tres subsets
con sus respectivos archivos de ground truth filtrados.

Uso:
    python scripts/create_subsets.py
"""

import json
import os
import random
import shutil
import sys

DATASET_DIR = "datasets/coco2017"
SUBSETS_DIR = "datasets/coco_subsets"
IMAGES_DIR = os.path.join(DATASET_DIR, "train2017")
ANNOTATIONS_FILE = os.path.join(DATASET_DIR, "annotations", "instances_train2017.json")

SIZES = [1000, 10000, 100000]
RANDOM_SEED = 42


def load_annotations(filepath: str) -> dict:
    """Carga el archivo JSON de anotaciones de COCO."""
    print(f"Cargando anotaciones desde {filepath}...")
    with open(filepath, "r") as f:
        data = json.load(f)
    print(f"  - {len(data['images'])} imagenes en el dataset original")
    print(f"  - {len(data['annotations'])} anotaciones")
    print(f"  - {len(data['categories'])} categorias")
    return data


def create_subset(
    coco_data: dict,
    size: int,
    output_dir: str
) -> None:
    """Crea un subset de 'size' imagenes con sus anotaciones filtradas."""
    print(f"\nCreando subset de {size} imagenes...")

    subset_images_dir = os.path.join(output_dir, "images")
    os.makedirs(subset_images_dir, exist_ok=True)

    all_images = coco_data["images"]
    all_annotations = coco_data["annotations"]
    categories = coco_data["categories"]

    random.seed(RANDOM_SEED)
    selected_images = random.sample(all_images, min(size, len(all_images)))
    selected_ids = {img["id"] for img in selected_images}

    filtered_annotations = [
        ann for ann in all_annotations if ann["image_id"] in selected_ids
    ]

    print(f"  Copiando {len(selected_images)} imagenes...")
    for img_info in selected_images:
        src = os.path.join(IMAGES_DIR, img_info["file_name"])
        dst = os.path.join(subset_images_dir, img_info["file_name"])
        if os.path.exists(src):
            if not os.path.exists(dst):
                try:
                    # Mismo volumen: evita copiar 111K JPEG y duplicar el espacio.
                    os.link(src, dst)
                except OSError:
                    shutil.copy2(src, dst)
        else:
            print(f"  Advertencia: {src} no existe, omitiendo.")

    subset_data = {
        "images": selected_images,
        "annotations": filtered_annotations,
        "categories": categories
    }

    annotations_out = os.path.join(output_dir, "instances_subset.json")
    with open(annotations_out, "w") as f:
        json.dump(subset_data, f)

    print(f"  Subset creado en {output_dir}")
    print(f"  - {len(selected_images)} imagenes")
    print(f"  - {len(filtered_annotations)} anotaciones")


def main() -> None:
    if not os.path.exists(IMAGES_DIR):
        print(f"Error: no se encontro {IMAGES_DIR}", file=sys.stderr)
        print("Ejecuta primero: python scripts/download_coco.py", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(ANNOTATIONS_FILE):
        print(f"Error: no se encontro {ANNOTATIONS_FILE}", file=sys.stderr)
        sys.exit(1)

    coco_data = load_annotations(ANNOTATIONS_FILE)

    for size in SIZES:
        output_dir = os.path.join(SUBSETS_DIR, f"coco{size // 1000}k")
        create_subset(coco_data, size, output_dir)

    print("\nSubsets creados correctamente.")


if __name__ == "__main__":
    main()
