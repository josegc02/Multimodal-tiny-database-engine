"""Entrena el vocabulario de Bag of Visual/Audio Words y lo guarda con su IDF.

1. Extrae los descriptores locales de cada archivo: todos los puntos SIFT de
   una imagen o un MFCC por ventana de un audio.
2. Entrena K-Means con hasta --sample descriptores muestreados de todos los
   archivos (los centroides son las palabras).
3. Calcula el IDF con el histograma de cada archivo de entrenamiento.

El resultado (models/bow_<tipo>_k<K>.npz por defecto) es el que usa
ExtractFeatures al insertar en columnas IMAGE y AUDIO.

Uso:
    python scripts/train_codebook.py --kind image --input datasets/bow_training/coco
    python scripts/train_codebook.py --kind audio --input datasets/bow_training/esc50
    python scripts/train_codebook.py --subset coco1k          # datasets/multimedia/coco1k/images
"""

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.features.bow import DEFAULT_K, DEFAULT_SAMPLE, BagOfWords  # noqa: E402
from engine.features.registry import vocabulary_path  # noqa: E402

DATASETS_DIR = ROOT / "datasets" / "multimedia"
EXTENSIONS = {"image": (".jpg", ".jpeg", ".png", ".bmp"), "audio": (".wav", ".mp3", ".flac", ".ogg")}


def describer(kind: str):
    if kind == "image":
        from engine.features.image.sift import SIFTExtractor
        extractor = SIFTExtractor(n_features=500)
        return extractor.extract_descriptors
    from engine.features.audio.mfcc import MFCCExtractor
    extractor = MFCCExtractor()
    return extractor.extract_frames


def local_descriptors(kind: str, files: list[Path], workers: int) -> list[np.ndarray]:
    describe = describer(kind)
    # OpenCV y librosa liberan el GIL en la parte costosa: los hilos aceleran la extracción.
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda path: describe(str(path)), files))


def train_codebook(kind: str, input_dir: Path, k: int = DEFAULT_K, sample: int = DEFAULT_SAMPLE,
                   output: Path | None = None, max_files: int | None = None, workers: int = 8,
                   seed: int = 42) -> BagOfWords:
    files = sorted(p for p in input_dir.iterdir() if p.suffix.lower() in EXTENSIONS[kind])[:max_files]
    if not files:
        raise SystemExit(f"No hay archivos de {kind} en {input_dir}")
    start = time.perf_counter()
    descriptors = local_descriptors(kind, files, workers)
    total = sum(len(d) for d in descriptors)
    print(f"{len(files)} archivos, {total} descriptores locales ({time.perf_counter() - start:.1f} s)")

    start = time.perf_counter()
    bow = BagOfWords.train(descriptors, k, sample=sample, seed=seed, kind=kind)
    print(f"K-Means K={k} con {min(total, sample)} descriptores ({time.perf_counter() - start:.1f} s)")

    vectors = [bow.transform(d) for d in descriptors]
    print(f"Palabras con IDF 0 (presentes en todos los archivos o en ninguno): {int(np.sum(bow.idf == 0))}/{k}")
    print(f"Archivos sin descriptores (vector en ceros): {sum(1 for v in vectors if not v.any())}")
    print(f"Palabras distintas por archivo (mediana): {int(np.median([np.count_nonzero(v) for v in vectors]))}")

    output = output or vocabulary_path(kind, k)
    output.parent.mkdir(parents=True, exist_ok=True)
    bow.save(output)
    print(f"Vocabulario guardado en {output}")
    return bow


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--kind", choices=("image", "audio"), default="image")
    parser.add_argument("--input", type=Path, help="carpeta con los archivos de entrenamiento")
    parser.add_argument("--subset", help="subconjunto COCO de #58 (datasets/multimedia/<subset>/images)")
    parser.add_argument("--k", type=int, default=DEFAULT_K)
    parser.add_argument("--sample", type=int, default=DEFAULT_SAMPLE)
    parser.add_argument("--max-files", type=int)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args(argv)
    if (args.input is None) == (args.subset is None):
        parser.error("indica --input o --subset")
    input_dir = args.input or DATASETS_DIR / args.subset / "images"
    if not input_dir.is_dir():
        parser.error(f"No existe {input_dir}")
    train_codebook(args.kind, input_dir, args.k, args.sample, args.output, args.max_files, args.workers)


if __name__ == "__main__":
    main()
