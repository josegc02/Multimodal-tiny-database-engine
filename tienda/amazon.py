"""Productos y compras desde Amazon Reviews 2023 (McAuley Lab, UCSD), issue #100.

Pasos, desde la raíz del repositorio::

    python -m tienda.amazon seleccionar            # productos_candidatos.csv
    python -m tienda.amazon compras                # compras.csv (después de tienda.imagenes)

``seleccionar`` descarga la metadata de una categoría (por defecto
Video_Games) y se queda con los productos que tienen precio, descripción e
imagen; de ellos toma los ``--cantidad`` con más reseñas. El archivo de
origen es una instantánea fija (2023), así que la selección es determinista.

``compras`` recorre las reseñas de la misma categoría: cada reseña con
``verified_purchase`` es una compra real de un usuario. Se conservan los
usuarios con al menos dos compras dentro del catálogo (los que aportan
pares "también compraron") hasta un máximo de filas.
"""

import argparse
import gzip
import hashlib
import heapq
import html
import json
import re
from collections import defaultdict
from pathlib import Path

from tienda.comun import GENERATED_DIR, RAW_DIR, descargar, escribir_csv, leer_csv

BASE_URL = "https://mcauleylab.ucsd.edu/public_datasets/data/amazon_2023/raw"
CATEGORIA = "Video_Games"
CANDIDATOS = GENERATED_DIR / "productos_candidatos.csv"
PRODUCTOS = GENERATED_DIR / "productos.csv"
COMPRAS = GENERATED_DIR / "compras.csv"

CAMPOS_CANDIDATOS = ("id", "asin", "titulo", "descripcion", "precio", "rating", "num_resenas",
                     "marca", "categoria", "url_imagen")
CAMPOS_COMPRAS = ("id", "usuario", "producto_id", "rating", "fecha")
MIN_PALABRAS = 15

_HTML = re.compile(r"<[^>]+>")
_ESPACIOS = re.compile(r"\s+")


def url_meta(categoria):
    return f"{BASE_URL}/meta_categories/meta_{categoria}.jsonl.gz"


def url_resenas(categoria):
    return f"{BASE_URL}/review_categories/{categoria}.jsonl.gz"


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


def compras(resenas_path, productos, min_compras=2, maximo=100_000):
    """Compras verificadas de los productos del catálogo.

    Una compra repetida del mismo usuario y producto cuenta una vez (la más
    antigua). Si hay más de ``maximo`` filas, se priorizan los usuarios con
    más compras, que son los que más informan a la recomendación.
    """
    id_por_asin = {fila["asin"]: int(fila["id"]) for fila in productos}
    por_usuario = defaultdict(dict)  # usuario -> {producto_id: (fecha, rating)}
    for resena in leer_jsonl(resenas_path):
        producto_id = id_por_asin.get(resena.get("parent_asin"))
        usuario = resena.get("user_id")
        if producto_id is None or not usuario or resena.get("verified_purchase") is not True:
            continue
        fecha = int(resena.get("timestamp") or 0) // 1000  # milisegundos -> segundos Unix
        anterior = por_usuario[usuario].get(producto_id)
        if anterior is None or fecha < anterior[0]:
            por_usuario[usuario][producto_id] = (fecha, float(resena.get("rating") or 0))

    usuarios = sorted((u for u, c in por_usuario.items() if len(c) >= min_compras),
                      key=lambda u: (-len(por_usuario[u]), u))
    filas = []
    for usuario in usuarios:
        if len(filas) + len(por_usuario[usuario]) > maximo:
            break
        filas += [(fecha, usuario, producto_id, rating)
                  for producto_id, (fecha, rating) in por_usuario[usuario].items()]
    filas.sort()
    return [{"id": numero, "usuario": usuario, "producto_id": producto_id, "rating": rating, "fecha": fecha}
            for numero, (fecha, usuario, producto_id, rating) in enumerate(filas, 1)]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Productos y compras de Amazon Reviews 2023 (issue #100)")
    sub = parser.add_subparsers(dest="comando", required=True)
    sel = sub.add_parser("seleccionar", help="descarga la metadata y elige los productos")
    sel.add_argument("--categoria", default=CATEGORIA)
    sel.add_argument("--cantidad", type=int, default=8000,
                     help="candidatos; tras descartar imágenes inválidas deben quedar 5 000-10 000")
    com = sub.add_parser("compras", help="descarga las reseñas y genera compras.csv")
    com.add_argument("--categoria", default=CATEGORIA)
    com.add_argument("--min-compras", type=int, default=2)
    com.add_argument("--maximo", type=int, default=100_000)
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
    else:
        from tienda.imagenes import CAMPOS_PRODUCTOS
        productos = leer_csv(PRODUCTOS, CAMPOS_PRODUCTOS)
        resenas = descargar(url_resenas(args.categoria), RAW_DIR / f"{args.categoria}.jsonl.gz")
        filas = compras(resenas, productos, args.min_compras, args.maximo)
        escribir_csv(COMPRAS, CAMPOS_COMPRAS, filas)
        usuarios = len({fila["usuario"] for fila in filas})
        print(f"{len(filas)} compras de {usuarios} usuarios en {COMPRAS}")


if __name__ == "__main__":
    main()