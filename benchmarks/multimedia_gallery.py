"""Galería HTML de consultas con recuperación alta y baja."""

import html
import json
import os
from pathlib import Path
from urllib.parse import quote


def write_gallery(output: Path, datasets: Path):
    rows = json.loads((output / "queries.json").read_text(encoding="utf-8"))
    if not rows:
        raise ValueError("No hay consultas para la galería")
    selected = []
    for size in sorted({r["size"] for r in rows}):
        for metric in ("euclidean", "cosine"):
            for technique in ("IVF", "HNSW"):
                group = [r for r in rows if (r["size"], r["metric"], r["technique"]) ==
                         (size, metric, technique)]
                if group:
                    selected.extend([max(group, key=lambda r: r["recall_at_10"]),
                                     min(group, key=lambda r: r["recall_at_10"])])
    def thumbnail(size, name):
        image = datasets / f"coco{size // 1000}k" / "images" / name
        if not image.is_file():
            raise FileNotFoundError(image)
        relative = os.path.relpath(image, output).replace("\\", "/")
        return f'<figure><img loading="lazy" src="{quote(relative)}" alt="{html.escape(name)}"><figcaption>{html.escape(name)}</figcaption></figure>'

    cards = []
    for row in selected:
        found = "".join(thumbnail(row["size"], name) for name in row["found_files"][:10])
        cards.append(f'<section><h2>{row["size"]} · {html.escape(row["metric"])} · '
                     f'{html.escape(row["technique"])} · Recall@10 {row["recall_at_10"]:.2f}</h2>'
                     f'<p>Consulta: {html.escape(row["category"])}</p>'
                     f'<div class="query">{thumbnail(row["size"], row["query_file"])}</div>'
                     f'<div class="results">{found}</div></section>')
    page = ('<!doctype html><html lang="es"><meta charset="utf-8"><title>Galería benchmark #59</title>'
            '<style>body{font:16px sans-serif;max-width:1200px;margin:auto;padding:2rem}'
            'section{border-top:1px solid #bbb;padding:1rem 0}figure{display:inline-block;margin:.3rem}'
            'img{width:140px;height:105px;object-fit:cover}.query img{width:280px;height:210px}'
            '.results{display:flex;flex-wrap:wrap}</style><h1>Casos de recuperación alta y baja</h1>'
            '<p>Recall@10 compara el índice aproximado con los diez vecinos exactos del mismo vector.</p>'
            + "".join(cards) + "</html>")
    (output / "gallery.html").write_text(page, encoding="utf-8")
