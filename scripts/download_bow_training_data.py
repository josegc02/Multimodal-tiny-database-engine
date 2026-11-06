"""Descarga los archivos con que se entrenan los vocabularios de Bag of Words.

- Imágenes: hasta --images fotos del subconjunto coco1k (#58), las que aparecen
  en benchmarks/results/multimedia/queries.json. Se bajan una por una desde
  images.cocodataset.org, sin el zip completo de COCO (~18 GB).
- Audio: --per-class clips de cada una de las 50 clases de ESC-50
  (K. J. Piczak, "ESC: Dataset for Environmental Sound Classification", 2015;
  licencia CC BY-NC 3.0), clips de 5 s a 44.1 kHz.

Los archivos quedan en datasets/bow_training/{coco,esc50}/, que git ignora.

Uso:
    python scripts/download_bow_training_data.py [--images 500] [--per-class 4]
"""

import argparse
import csv
import io
import json
import sys
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "datasets" / "bow_training"
QUERIES = ROOT / "benchmarks" / "results" / "multimedia" / "queries.json"
COCO_URL = "http://images.cocodataset.org/train2017/{}"
ESC50_META = "https://raw.githubusercontent.com/karolpiczak/ESC-50/master/meta/esc50.csv"
ESC50_AUDIO = "https://github.com/karolpiczak/ESC-50/raw/master/audio/{}"
USER_AGENT = {"User-Agent": "bd2-multimodal-engine/1.0"}


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers=USER_AGENT)
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def download_all(items, directory: Path) -> int:
    """Baja (nombre, url) que todavía no existan; devuelve cuántos archivos hay."""
    directory.mkdir(parents=True, exist_ok=True)
    pending = [(name, url) for name, url in items if not (directory / name).exists()]

    def save(item):
        name, url = item
        data = fetch(url)
        (directory / name).write_bytes(data)

    with ThreadPoolExecutor(max_workers=8) as pool:
        for done, _ in enumerate(pool.map(save, pending), 1):
            if done % 50 == 0 or done == len(pending):
                print(f"  {done}/{len(pending)}")
    return sum(1 for name, _ in items if (directory / name).exists())


def coco_files(limit: int) -> list[str]:
    entries = json.loads(QUERIES.read_text(encoding="utf-8"))
    names = set()
    for entry in entries:
        if entry["size"] == 1000:
            names.update([entry["query_file"], *entry["exact_files"], *entry["found_files"]])
    return sorted(names)[:limit]


def esc50_files(per_class: int) -> list[str]:
    rows = csv.DictReader(io.StringIO(fetch(ESC50_META).decode("utf-8")))
    by_class = defaultdict(list)
    for row in rows:
        by_class[row["category"]].append(row["filename"])
    return sorted(name for names in by_class.values() for name in sorted(names)[:per_class])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--images", type=int, default=500)
    parser.add_argument("--per-class", type=int, default=4)
    args = parser.parse_args(argv)

    images = coco_files(args.images)
    print(f"Imágenes COCO: {len(images)}")
    total = download_all([(name, COCO_URL.format(name)) for name in images], OUTPUT / "coco")
    print(f"  listas: {total}")

    clips = esc50_files(args.per_class)
    print(f"Clips ESC-50: {len(clips)}")
    total = download_all([(name, ESC50_AUDIO.format(name)) for name in clips], OUTPUT / "esc50")
    print(f"  listos: {total}")


if __name__ == "__main__":
    sys.exit(main())
