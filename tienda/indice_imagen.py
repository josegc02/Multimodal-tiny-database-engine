"""Índice HNSW auxiliar para la representación IMAGE MobileNet.

Tiene su propio lock: la extracción de vectores (minutos con el catálogo completo)
no se hace dentro del lock del motor, así que no bloquea al resto de la API.
Para no esperar en la primera petición, precalcule los vectores antes de la demo:

    python -m tienda.indice_imagen --datos data/app
"""
import argparse
import hashlib
import os
import tempfile
import threading
import time
from pathlib import Path

import numpy as np

from engine.features.image.mobilenet import SHA256
from engine.features.registry import extract_features, extractor_for
from engine.indexes.hnsw import HNSWIndex


class ImageIndex:
    # Revisar los 7,995 archivos de imagen (stat de cada uno) tarda ~3.5 s: se hace como
    # mucho una vez por este intervalo, no en cada recomendación.
    REVISION_S = 60

    def __init__(self, directory):
        self.directory = Path(directory) / "mobilenet"
        self.signature = None
        self.index = None
        self._revisado = None  # time.monotonic() de la última revisión completa
        self.omitidos = []  # (id, motivo) de las imágenes que no se pudieron leer
        self._lock = threading.Lock()

    def vigente(self):
        """True si el índice existe y se revisó hace menos de REVISION_S segundos."""
        return (self.index is not None and self._revisado is not None
                and time.monotonic() - self._revisado < self.REVISION_S)

    def actualizar(self, filas):
        """Pone el índice al día con el catálogo. Una imagen ilegible se omite, no detiene a las demás.

        Si falta el modelo MobileNet se lanza el error, porque afecta a todo el índice.
        """
        with self._lock:
            extractor_for("image", "mobilenet")  # sin modelo: error claro antes de recorrer el catálogo
            firma, omitidos = [], []
            for fila in sorted(filas, key=lambda f: f["id"]):
                try:
                    path = Path(fila["imagen"]).resolve()
                    stat = path.stat()
                except (OSError, TypeError) as exc:
                    omitidos.append((fila["id"], f"sin archivo: {exc}"))
                    continue
                firma.append((fila["id"], str(path), stat.st_size, stat.st_mtime_ns))
            firma = tuple(firma)
            if firma == self.signature:
                self._revisado = time.monotonic()
                return
            nuevo = HNSWIndex(metric="cosine")
            self.directory.mkdir(parents=True, exist_ok=True)
            for identificador, path, size, modified in firma:
                try:
                    vector = self._vector(path, size, modified)
                except (OSError, ValueError) as exc:
                    omitidos.append((identificador, str(exc)))
                    continue
                nuevo.insert(identificador, vector)
            self.index, self.signature, self.omitidos = nuevo, firma, omitidos
            self._revisado = time.monotonic()

    def _vector(self, path, size, modified):
        key = hashlib.sha256(repr((SHA256, path, size, modified)).encode()).hexdigest()
        destino = self.directory / (key + ".npy")
        if destino.exists():
            return np.load(destino, allow_pickle=False)
        vector = extract_features("image", path, "mobilenet")
        with tempfile.NamedTemporaryFile(dir=self.directory, suffix=".tmp", delete=False) as stream:
            temporal = Path(stream.name)
            np.save(stream, vector, allow_pickle=False)
        try:
            os.replace(temporal, destino)
        finally:
            temporal.unlink(missing_ok=True)
        return vector

    def buscar(self, identificador, k=51):
        """Similitud coseno de los k más parecidos; vacío si el producto no está en el índice."""
        with self._lock:
            if self.index is None or identificador not in self.index.vectors:
                return {}
            vector = self.index.vectors[identificador]
            return dict(self.index.search(vector, k=k, ef_search=max(50, k)).matches)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Precalcula los vectores MobileNet del catálogo")
    parser.add_argument("--datos", default="data/app", help="carpeta de datos del motor (la de la API)")
    args = parser.parse_args(argv)
    from frontend.motor import Motor
    from tienda.recomendaciones import consultar

    motor = Motor(directorio=args.datos, modo_demo=False)
    try:
        filas = consultar(motor, "SELECT id, imagen FROM productos")
        indice = ImageIndex(motor.directorio)
    finally:
        motor.cerrar()
    indice.actualizar(filas)
    print(f"{len(indice.index.vectors)} vectores en {indice.directory}; {len(indice.omitidos)} imágenes omitidas")
    for identificador, motivo in indice.omitidos[:10]:
        print(f"  producto {identificador}: {motivo}")


if __name__ == "__main__":
    main()
