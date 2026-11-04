"""
Script para entrenar el codebook (vocabulario visual) usando el dataset COCO.
Extrae SIFT de un subset, entrena K-Means y guarda los centroides y el IDF.
"""
import argparse
import json
import numpy as np
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine.features.image.kmeans import KMeans
from engine.features.image.bovw import BoVWExtractor
from engine.features.image.sift import SIFTExtractor

DATASETS_DIR = PROJECT_ROOT / "datasets" / "coco_subsets"

def train_codebook(subset_name: str, k: int = 100, max_images: int = 200):
    print(f"Entrenando codebook K={k} con {subset_name}...")
    subset_dir = DATASETS_DIR / subset_name
    images_dir = subset_dir / "images"
    
    if not images_dir.exists():
        print(f"Error: No existe {images_dir}")
        sys.exit(1)

    # 1. Extraer descriptores SIFT crudos
    extractor = SIFTExtractor(n_features=500)
    all_descriptors = []
    image_files = sorted(list(images_dir.glob("*.jpg")))[:max_images] # Limitar para velocidad
    
    print(f"Extrayendo SIFT de {len(image_files)} imágenes...")
    for img_path in image_files:
        try:
            desc = extractor.extract(str(img_path))
            all_descriptors.append(desc)
        except Exception as e:
            continue

    if not all_descriptors:
        print("No se pudieron extraer descriptores.")
        sys.exit(1)

    X = np.array(all_descriptors, dtype=float)
    print(f"Matriz de entrenamiento: {X.shape}")

    # 2. Entrenar K-Means
    print("Entrenando K-Means...")
    kmeans = KMeans(k=k, max_iter=50, random_state=42)
    kmeans.fit(X)
    
    # 3. Guardar Codebook
    codebook_path = subset_dir / f"codebook_k{k}.npy"
    kmeans.save(str(codebook_path))
    print(f"Codebook guardado en: {codebook_path}")

    # 4. Calcular y guardar IDF (usando los mismos datos de entrenamiento)
    print("Calculando IDF...")
    bovw = BoVWExtractor(k=k, codebook_path=str(codebook_path))
    histograms = [bovw.compute_histogram(desc.reshape(1, -1)) for desc in X]
    bovw.compute_idf(histograms)
    
    idf_path = subset_dir / f"idf_k{k}.npy"
    np.save(str(idf_path), bovw.idf)
    print(f"IDF guardado en: {idf_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--subset", type=str, default="coco1k")
    parser.add_argument("--k", type=int, default=100)
    args = parser.parse_args()
    train_codebook(args.subset, args.k)