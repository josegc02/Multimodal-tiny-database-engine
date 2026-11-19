"""Descarga y validación de las imágenes de productos (issue #100).

Lee ``productos_candidatos.csv``, descarga la imagen de cada producto a
``datasets/tienda/imagenes/<asin>.jpg`` y la valida igual que la usará el
motor: OpenCV debe poder abrirla, medir al menos 100 px por lado y tener
puntos SIFT suficientes para su vector Bag of Visual Words. Los productos
sin imagen válida se descartan; los demás se renumeran desde 1 en
``productos.csv`` con la ruta absoluta de su imagen (columna ``imagen``).

Uso::

    python -m tienda.imagenes
"""

import argparse
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from tienda.amazon import CANDIDATOS, CAMPOS_CANDIDATOS, PRODUCTOS
from tienda.comun import GENERATED_DIR, IMAGENES_DIR, USER_AGENT, escribir_csv, leer_csv

CAMPOS_PRODUCTOS = CAMPOS_CANDIDATOS + ("imagen",)
DESCARTADOS = GENERATED_DIR / "imagenes_descartadas.csv"
LADO_MINIMO = 100
PUNTOS_MINIMOS = 10


def validar(datos):
    """None si la imagen sirve; si no, el motivo del descarte."""
    import cv2
    import numpy as np

    if not datos:
        return "vacía"
    imagen = cv2.imdecode(np.frombuffer(datos, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if imagen is None:
        return "no se puede decodificar"
    if min(imagen.shape[:2]) < LADO_MINIMO:
        return f"menor a {LADO_MINIMO} px"
    if len(cv2.SIFT_create(nfeatures=500).detect(imagen, None)) < PUNTOS_MINIMOS:
        return "sin puntos SIFT suficientes"
    return None


def bajar(url, intentos=3, abrir=urllib.request.urlopen):
    for intento in range(intentos):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with abrir(request, timeout=30) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404 or intento == intentos - 1:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if intento == intentos - 1:
                raise
        time.sleep(2 ** intento)
    return b""


def procesar(fila, destino, descargar=bajar):
    """(fila, motivo): descarga si hace falta, valida y guarda en disco."""
    path = Path(destino) / f"{fila['asin']}.jpg"
    try:
        datos = path.read_bytes() if path.is_file() else descargar(fila["url_imagen"])
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        return fila, f"error de descarga ({exc})"
    motivo = validar(datos)
    if motivo is None and not path.is_file():
        temporal = path.with_name(path.name + ".part")
        temporal.write_bytes(datos)
        temporal.replace(path)
    return fila, motivo


def filtrar(candidatos, destino=IMAGENES_DIR, hilos=8, descargar=bajar, log=print):
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    validos, descartados = {}, []
    with ThreadPoolExecutor(max_workers=hilos) as pool:
        trabajos = pool.map(lambda fila: procesar(fila, destino, descargar), candidatos)
        for numero, (fila, motivo) in enumerate(trabajos, 1):
            if motivo is None:
                validos[fila["asin"]] = fila
            else:
                descartados.append({"asin": fila["asin"], "motivo": motivo})
            if numero % 250 == 0:
                log(f"{numero}/{len(candidatos)} imágenes, {len(descartados)} descartadas")
    # Se respeta el orden de los candidatos (más reseñas primero) y se renumera.
    productos = []
    for fila in candidatos:
        if fila["asin"] in validos:
            imagen = str((destino / f"{fila['asin']}.jpg").resolve())
            productos.append({**fila, "id": len(productos) + 1, "imagen": imagen})
    return productos, descartados


def main(argv=None):
    parser = argparse.ArgumentParser(description="Descarga y valida imágenes de productos (issue #100)")
    parser.add_argument("--hilos", type=int, default=8)
    args = parser.parse_args(argv)
    candidatos = leer_csv(CANDIDATOS, CAMPOS_CANDIDATOS)
    productos, descartados = filtrar(candidatos, hilos=args.hilos)
    escribir_csv(PRODUCTOS, CAMPOS_PRODUCTOS, productos)
    escribir_csv(DESCARTADOS, ("asin", "motivo"), descartados)
    print(f"{len(productos)} productos con imagen válida en {PRODUCTOS}; "
          f"{len(descartados)} descartados (ver {DESCARTADOS})")
    if not 5000 <= len(productos) <= 10_000:
        parser.exit(1, "Error: deben quedar entre 5 000 y 10 000 productos; ajuste --cantidad al seleccionar\n")


if __name__ == "__main__":
    main()