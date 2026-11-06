"""Galería HTML con casos de éxito y de error de la búsqueda por similitud.

Hay dos lecturas de "éxito" y se muestran por separado para cada tamaño,
métrica e índice:

- Semántica: una imagen devuelta acierta si comparte alguna categoría COCO con
  la categoría de la consulta (anotaciones de instances_subset.json). Se
  muestran la consulta con mayor y con menor precisión semántica.
- Del índice: Recall@10 frente a los diez vecinos exactos del mismo vector,
  es decir, cuánto pierde la búsqueda aproximada. Se muestran la mejor y la peor.

Si el subconjunto no tiene anotaciones, la galería se genera sin la parte semántica.
"""

import html
import json
import os
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote

STYLE = (
    "body{font:15px sans-serif;max-width:1240px;margin:auto;padding:2rem;color:#1c2d40}"
    "section{border-top:1px solid #bbb;padding:1rem 0}h2{font-size:1.05rem;margin:.2rem 0}"
    ".tag{display:inline-block;padding:.1rem .5rem;border-radius:4px;margin-right:.4rem;color:#fff;font-size:.85rem}"
    ".exito{background:#1f7a3f}.error{background:#a62532}.indice{background:#145ba8}"
    "figure{display:inline-block;margin:.3rem;vertical-align:top;width:150px}"
    "figure img{width:146px;height:110px;object-fit:cover;border:4px solid #ccc;border-radius:4px}"
    "figure.hit img{border-color:#1f9d55}figure.miss img{border-color:#d64545}"
    "figcaption{font-size:.75rem;overflow-wrap:anywhere}.query figure{width:300px}"
    ".query figure img{width:292px;height:220px;border-color:#145ba8}.results{display:flex;flex-wrap:wrap}"
    "table{border-collapse:collapse;margin:1rem 0}td,th{border:1px solid #bbb;padding:.3rem .6rem;text-align:right}"
    "th:first-child,td:first-child{text-align:left}"
)


def load_categories(datasets: Path, size: int) -> dict | None:
    """file_name -> conjunto de categorías COCO de la imagen, o None sin anotaciones."""
    manifest = datasets / f"coco{size // 1000}k" / "instances_subset.json"
    if not manifest.is_file():
        return None
    data = json.loads(manifest.read_text(encoding="utf-8"))
    names = {category["id"]: category["name"] for category in data.get("categories", [])}
    by_image = defaultdict(set)
    for annotation in data.get("annotations", []):
        by_image[annotation["image_id"]].add(names.get(annotation["category_id"], "?"))
    return {image["file_name"]: by_image.get(image["id"], set()) for image in data["images"]}


def semantic_hits(row: dict, categories: dict) -> list[bool]:
    """Para cada imagen devuelta, si comparte la categoría de la consulta."""
    return [row["category"] in categories.get(name, set()) for name in row["found_files"]]


def write_gallery(output: Path, datasets: Path):
    rows = json.loads((output / "queries.json").read_text(encoding="utf-8"))
    if not rows:
        raise ValueError("No hay consultas para la galería")
    categories = {size: load_categories(datasets, size) for size in sorted({r["size"] for r in rows})}
    for row in rows:
        known = categories[row["size"]]
        hits = semantic_hits(row, known) if known is not None else None
        row["_hits"] = hits
        row["_precision"] = sum(hits) / len(hits) if hits else None

    def thumbnail(size, name, hit=None):
        image = datasets / f"coco{size // 1000}k" / "images" / name
        if not image.is_file():
            raise FileNotFoundError(image)
        relative = os.path.relpath(image, output).replace("\\", "/")
        known = categories[size]
        labels = ", ".join(sorted(known.get(name, ()))[:3]) if known is not None else ""
        css = "" if hit is None else (' class="hit"' if hit else ' class="miss"')
        caption = html.escape(labels or name)
        return (f'<figure{css}><img loading="lazy" src="{quote(relative)}" alt="{html.escape(name)}">'
                f'<figcaption>{caption}</figcaption></figure>')

    def card(row, kind, label):
        hits = row["_hits"] or [None] * len(row["found_files"])
        found = "".join(thumbnail(row["size"], name, hit) for name, hit in zip(row["found_files"][:10], hits))
        precision = "" if row["_precision"] is None else f' · Precisión semántica@10 {row["_precision"]:.2f}'
        return (f'<section><h2><span class="tag {kind}">{label}</span>{row["size"]} · '
                f'{html.escape(row["metric"])} · {html.escape(row["technique"])} · '
                f'Recall@10 {row["recall_at_10"]:.2f}{precision}</h2>'
                f'<p>Consulta: <b>{html.escape(row["category"])}</b></p>'
                f'<div class="query">{thumbnail(row["size"], row["query_file"])}</div>'
                f'<div class="results">{found}</div></section>')

    cards, summary = [], []
    for size in sorted(categories):
        for metric in ("euclidean", "cosine"):
            for technique in ("IVF", "HNSW"):
                group = [r for r in rows if (r["size"], r["metric"], r["technique"]) == (size, metric, technique)]
                if not group:
                    continue
                chosen = []
                if group[0]["_precision"] is not None:
                    by_precision = sorted(group, key=lambda r: (r["_precision"], r["recall_at_10"]))
                    chosen += [(by_precision[-1], "exito", "Éxito"), (by_precision[0], "error", "Error")]
                    mean = sum(r["_precision"] for r in group) / len(group)
                    summary.append((size, metric, technique, mean,
                                    sum(r["recall_at_10"] for r in group) / len(group)))
                by_recall = sorted(group, key=lambda r: r["recall_at_10"])
                chosen += [(by_recall[-1], "indice", "Mejor recall del índice"),
                           (by_recall[0], "indice", "Peor recall del índice")]
                seen = set()
                for row, kind, label in chosen:
                    if id(row) not in seen:
                        seen.add(id(row))
                        cards.append(card(row, kind, label))

    intro = ('<p><b>Éxito / Error</b>: consultas con mayor y menor precisión semántica, es decir, cuántas '
             'de las 10 imágenes devueltas comparten la categoría COCO de la consulta (borde verde) o no '
             '(borde rojo). <b>Recall del índice</b>: cuánto coincide el índice aproximado con los diez '
             'vecinos exactos del mismo vector.</p>')
    table = ""
    if summary:
        lines = "".join(f"<tr><td>{s} · {m} · {t}</td><td>{p:.3f}</td><td>{r:.3f}</td></tr>"
                        for s, m, t, p, r in summary)
        table = ("<table><tr><th>Configuración</th><th>Precisión semántica@10 media</th>"
                 f"<th>Recall@10 medio</th></tr>{lines}</table>")
    page = ('<!doctype html><html lang="es"><meta charset="utf-8"><title>Galería benchmark #59</title>'
            f"<style>{STYLE}</style><h1>Casos de éxito y error</h1>{intro}{table}"
            + "".join(cards) + "</html>")
    (output / "gallery.html").write_text(page, encoding="utf-8")
