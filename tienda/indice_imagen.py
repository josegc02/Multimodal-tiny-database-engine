"""Índice HNSW auxiliar para la representación IMAGE MobileNet."""
import hashlib
import os
import tempfile
from pathlib import Path

import numpy as np

from engine.features.image.mobilenet import SHA256
from engine.features.registry import extract_features
from engine.indexes.hnsw import HNSWIndex


class ImageIndex:
    """El llamador mantiene el lock del motor durante actualización y búsqueda."""
    def __init__(self, directory):
        self.directory = Path(directory) / "mobilenet"
        self.signature = None
        self.index = None

    def actualizar(self, filas):
        firma = []
        for fila in sorted(filas, key=lambda f: f["id"]):
            path = Path(fila["imagen"]).resolve()
            stat = path.stat()
            firma.append((fila["id"], str(path), stat.st_size, stat.st_mtime_ns))
        firma = tuple(firma)
        if firma == self.signature:
            return
        nuevo = HNSWIndex(metric="cosine")
        self.directory.mkdir(parents=True, exist_ok=True)
        for identificador, path, size, modified in firma:
            key = hashlib.sha256(repr((SHA256, path, size, modified)).encode()).hexdigest()
            destino = self.directory / (key + ".npy")
            if destino.exists():
                vector = np.load(destino, allow_pickle=False)
            else:
                vector = extract_features("image", path, "mobilenet")
                with tempfile.NamedTemporaryFile(dir=self.directory, suffix=".tmp", delete=False) as stream:
                    temporal = Path(stream.name)
                    np.save(stream, vector, allow_pickle=False)
                try:
                    os.replace(temporal, destino)
                finally:
                    temporal.unlink(missing_ok=True)
            nuevo.insert(identificador, vector)
        self.index, self.signature = nuevo, firma

    def buscar(self, identificador, k=51):
        vector = self.index.vectors[identificador]
        return dict(self.index.search(vector, k=k, ef_search=max(50, k)).matches)
