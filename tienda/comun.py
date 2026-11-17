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
    """Descarga por bloques a un .part y lo renombra al terminar; si ya existe, no hace nada."""
    destino = Path(destino)
    if destino.is_file():
        return destino
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_name(destino.name + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    total, siguiente = 0, 50 * 2**20
    with abrir(request, timeout=120) as response, temporal.open("wb") as stream:
        while bloque := response.read(2**20):
            stream.write(bloque)
            total += len(bloque)
            if total >= siguiente:
                log(f"{destino.name}: {total // 2**20} MB")
                siguiente += 50 * 2**20
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