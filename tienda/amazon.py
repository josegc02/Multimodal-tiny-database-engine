"""Productos desde Amazon Reviews 2023 (McAuley Lab, UCSD), issue #100.

Pasos, desde la raíz del repositorio::

    python -m tienda.amazon seleccionar            # productos_candidatos.csv

``seleccionar`` descarga la metadata de una categoría (por defecto
Video_Games) y se queda con los productos que tienen precio, descripción e
imagen; de ellos toma los ``--cantidad`` con más reseñas. El archivo de
origen es una instantánea fija (2023), así que la selección es determinista.
"""

import argparse
import gzip
import hashlib
import heapq
import html
import json
import re
from pathlib import Path

from tienda.comun import GENERATED_DIR, RAW_DIR, descargar, escribir_csv

BASE_URL = "https://mcauleylab.ucsd.edu/public_datasets/data/amazon_2023/raw"
CATEGORIA = "Video_Games"
CANDIDATOS = GENERATED_DIR / "productos_candidatos.csv"
PRODUCTOS = GENERATED_DIR / "productos.csv"  # lo escribe tienda.imagenes

CAMPOS_CANDIDATOS = ("id", "asin", "titulo", "descripcion", "precio", "rating", "num_resenas",
                     "marca", "categoria", "url_imagen")
MIN_PALABRAS = 15

_HTML = re.compile(r"<[^>]+>")
_ESPACIOS = re.compile(r"\s+")


def url_meta(categoria):
    return f"{BASE_URL}/meta_categories/meta_{categoria}.jsonl.gz"


def leer_jsonl(path):
    """Recorre un .jsonl.gz línea por línea sin cargarlo entero en memoria."""
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for linea in stream:
            if linea.strip():
                yield json.loads(linea)


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def texto_limpio(partes):
    """Une listas de párrafos, quita etiquetas HTML y espacios repetidos."""
    if isinstance(partes, str):
        partes = [partes]
    texto = " ".join(str(parte) for parte in partes or [] if parte)
    return _ESPACIOS.sub(" ", html.unescape(_HTML.sub(" ", texto))).strip()


def precio(valor):
    try:
        numero = float(str(valor).replace("$", "").replace(",", ""))
    except (TypeError, ValueError):
        return None
    return round(numero, 2) if 0 < numero < 100_000 else None


def url_imagen(imagenes):
    """Imagen principal en tamaño 'large' (~500 px); si falta, la de alta resolución."""
    imagenes = [imagen for imagen in imagenes or [] if isinstance(imagen, dict)]
    imagenes.sort(key=lambda imagen: imagen.get("variant") != "MAIN")  # MAIN primero
    for imagen in imagenes:
        for campo in ("large", "hi_res", "thumb"):
            url = imagen.get(campo)
            if isinstance(url, str) and url.startswith("http"):
                return url
    return None


def producto(meta):
    """Fila de candidato o None si al producto le falta precio, descripción o imagen."""
    asin, titulo = meta.get("parent_asin"), texto_limpio(meta.get("title"))
    descripcion = f'{texto_limpio(meta.get("description"))} {texto_limpio(meta.get("features"))}'.strip()
    valor, imagen = precio(meta.get("price")), url_imagen(meta.get("images"))
    if not asin or not titulo or valor is None or imagen is None or len(descripcion.split()) < MIN_PALABRAS:
        return None
    categorias = [c for c in meta.get("categories") or [] if isinstance(c, str)]
    return {
        "asin": asin,
        "titulo": titulo,
        "descripcion": descripcion,
        "precio": valor,
        "rating": float(meta.get("average_rating") or 0),
        "num_resenas": int(meta.get("rating_number") or 0),
        "marca": texto_limpio(meta.get("store")) or "Desconocida",
        "categoria": " > ".join(categorias) or texto_limpio(meta.get("main_category")) or "Video Games",
        "url_imagen": imagen,
    }


def seleccionar(meta_path, cantidad):
    """Los ``cantidad`` productos válidos con más reseñas; empates por ASIN."""
    vistos = set()

    def validos():
        for meta in leer_jsonl(meta_path):
            fila = producto(meta)
            if fila and fila["asin"] not in vistos:
                vistos.add(fila["asin"])
                yield fila

    elegidos = heapq.nsmallest(cantidad, validos(), key=lambda f: (-f["num_resenas"], f["asin"]))
    return [{"id": numero, **fila} for numero, fila in enumerate(elegidos, 1)]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Productos de Amazon Reviews 2023 (issue #100)")
    sub = parser.add_subparsers(dest="comando", required=True)
    sel = sub.add_parser("seleccionar", help="descarga la metadata y elige los productos")
    sel.add_argument("--categoria", default=CATEGORIA)
    sel.add_argument("--cantidad", type=int, default=8000,
                     help="candidatos; tras descartar imágenes inválidas deben quedar 5 000-10 000")
    args = parser.parse_args(argv)

    if args.comando == "seleccionar":
        if not 5000 <= args.cantidad <= 20_000:
            parser.error("--cantidad debe estar entre 5 000 y 20 000")
        meta = descargar(url_meta(args.categoria), RAW_DIR / f"meta_{args.categoria}.jsonl.gz")
        filas = seleccionar(meta, args.cantidad)
        escribir_csv(CANDIDATOS, CAMPOS_CANDIDATOS, filas)
        print(f"{len(filas)} candidatos en {CANDIDATOS} (sha256 del origen: {sha256(meta)[:16]}…)")
        if len(filas) < args.cantidad:
            print(f"Aviso: solo {len(filas)} productos cumplen los filtros")


if __name__ == "__main__":
    main()