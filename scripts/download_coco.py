"""
Script para descargar y descomprimir el dataset MS-COCO 2017.

Descarga:
- train2017.zip (imagenes de entrenamiento, ~118K imagenes)
- annotations_trainval2017.zip (ground truth)

Uso:
    python scripts/download_coco.py
"""

import os
import sys
import urllib.request
import zipfile


DATASET_DIR = "datasets/coco2017"

IMAGES_URL = "http://images.cocodataset.org/zips/train2017.zip"
IMAGES_ZIP = os.path.join(DATASET_DIR, "train2017.zip")

ANNOTATIONS_URL = "http://images.cocodataset.org/annotations/annotations_trainval2017.zip"
ANNOTATIONS_ZIP = os.path.join(DATASET_DIR, "annotations_trainval2017.zip")


def download_file(url: str, dest: str) -> None:
    """Descarga un archivo desde una URL hacia una ruta local."""
    print(f"Descargando {url}...")
    try:
        urllib.request.urlretrieve(url, dest)
        print(f"Descarga completada: {dest}")
    except Exception as e:
        print(f"Error al descargar {url}: {e}", file=sys.stderr)
        sys.exit(1)


def unzip_file(filepath: str, extract_dir: str) -> None:
    """Descomprime un archivo ZIP en el directorio indicado."""
    print(f"Descomprimiendo {filepath}...")
    try:
        with zipfile.ZipFile(filepath, "r") as zf:
            zf.extractall(extract_dir)
        print(f"Extraccion completada en {extract_dir}")
    except Exception as e:
        print(f"Error al descomprimir {filepath}: {e}", file=sys.stderr)
        sys.exit(1)


def download_coco() -> None:
    """Descarga y descomprime MS-COCO 2017 si no existe localmente."""
    os.makedirs(DATASET_DIR, exist_ok=True)

    if not os.path.exists(IMAGES_ZIP):
        download_file(IMAGES_URL, IMAGES_ZIP)
        unzip_file(IMAGES_ZIP, DATASET_DIR)
        os.remove(IMAGES_ZIP)
        print("Archivo zip de imagenes eliminado.")
    else:
        print(f"{IMAGES_ZIP} ya existe, omitiendo descarga de imagenes.")

    if not os.path.exists(ANNOTATIONS_ZIP):
        download_file(ANNOTATIONS_URL, ANNOTATIONS_ZIP)
        unzip_file(ANNOTATIONS_ZIP, DATASET_DIR)
        os.remove(ANNOTATIONS_ZIP)
        print("Archivo zip de anotaciones eliminado.")
    else:
        print(f"{ANNOTATIONS_ZIP} ya existe, omitiendo descarga de anotaciones.")

    print("Dataset MS-COCO 2017 listo.")


if __name__ == "__main__":
    download_coco()