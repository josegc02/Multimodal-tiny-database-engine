"""Rutas y utilidades compartidas por los scripts de datos de la tienda."""

import csv
import os
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASET_DIR = ROOT / "datasets" / "tienda"
RAW_DIR = DATASET_DIR / "raw"            # archivos originales descargados (no se versionan)
GENERATED_DIR = DATASET_DIR / "generated"  # CSV listos para COPY (no se versionan)
IMAGENES_DIR = DATASET_DIR / "imagenes"    # imágenes de productos (no se versionan)
USER_AGENT = "multimodal-tiny-database-engine/1.0 (proyecto academico BD2)"


def descargar(url, destino, log=print, abrir=urllib.request.urlopen):
    """Descarga por bloques y reanuda el .part si el servidor acepta Range."""
    destino = Path(destino)
    if destino.is_file():
        return destino
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_name(destino.name + ".part")
    inicio = temporal.stat().st_size if temporal.exists() else 0
    headers = {"User-Agent": USER_AGENT}
    if inicio:
        headers["Range"] = f"bytes={inicio}-"
    request = urllib.request.Request(url, headers=headers)
    with abrir(request, timeout=120) as response:
        parcial = getattr(response, "status", 200) == 206
        if parcial:
            content_range = response.headers.get("Content-Range", "")
            if not content_range.startswith(f"bytes {inicio}-"):
                raise IOError(f"El servidor devolvió un rango inesperado: {content_range}")
            esperado = int(content_range.rsplit("/", 1)[1])
            modo = "ab"
            total = inicio
        else:
            esperado = int(response.headers.get("Content-Length", 0))
            modo = "wb"  # servidor sin Range: empezar desde cero
            total = 0
        siguiente = ((total // (50 * 2**20)) + 1) * 50 * 2**20
        with temporal.open(modo) as stream:
            while bloque := response.read(2**20):
                stream.write(bloque)
                total += len(bloque)
                if total >= siguiente:
                    log(f"{destino.name}: {total // 2**20} MB")
                    siguiente += 50 * 2**20
    if esperado and total != esperado:
        raise IOError(f"Descarga incompleta de {destino.name}: {total} de {esperado} bytes")
    os.replace(temporal, destino)
    log(f"{destino.name}: listo ({total // 2**20} MB)")
    return destino


def escribir_csv(path, campos, filas):
    """Escribe UTF-8 con cabecera en un archivo temporal y lo reemplaza al final."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporal = path.with_name(path.name + ".tmp")
    cantidad = 0
    with temporal.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=campos)
        writer.writeheader()
        for fila in filas:
            writer.writerow(fila)
            cantidad += 1
    os.replace(temporal, path)
    return cantidad


def leer_csv(path, campos):
    """Lee un CSV y verifica que su cabecera sea exactamente ``campos``."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"No existe {path}; ejecute antes el paso que lo genera")
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != tuple(campos):
            raise ValueError(f"Cabecera incorrecta en {path}; se esperaba {tuple(campos)}")
        return list(reader)
