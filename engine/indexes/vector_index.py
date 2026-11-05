"""Índice vectorial (HNSW o IVF) sobre una columna IMAGE o AUDIO.

Adapta HNSWIndex e IVFIndex al contrato de índices del catálogo: insert/delete
por (ruta, RID), search(ruta) y bulk_load_from_storage. Los vectores salen del
MediaStore de la tabla, donde se guardaron al insertar.

- HNSW no permite borrar nodos: un borrado deja una marca y la búsqueda pide
  más vecinos para compensar. Cuando las marcas superan a los nodos vivos, el
  grafo se reconstruye.
- IVF necesita entrenar sus centroides. Con menos de MIN_TRAIN vectores se
  busca de forma exacta; luego se entrena con nlist ≈ √N y se vuelve a entrenar
  cada vez que la colección duplica el tamaño del último entrenamiento. Si las
  nprobe listas revisadas no reúnen k vectores, se revisan más listas.

SIMILARITY_SCORE() siempre crece con la similitud: el coseno y el producto
punto se devuelven tal cual y la distancia euclidiana d como 1 / (1 + d).

El índice vive en memoria y se reconstruye desde la tabla al registrarse;
close() guarda el grafo o los centroides en `filepath` (formato JSON de
HNSWIndex/IVFIndex) para medir su tamaño en disco.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set, Tuple

import numpy as np

from engine.indexes.hnsw import HNSWIndex
from engine.indexes.ivf import IVFIndex

METRICS = ("euclidean", "cosine", "dot")
METHODS = ("hnsw", "ivf")
_INNER_METRIC = {"euclidean": "euclidean", "cosine": "cosine", "dot": "dot_product"}

HNSW_M = 8
HNSW_EF_CONSTRUCTION = 50
HNSW_EF_SEARCH = 50
MIN_TRAIN = 16  # IVF busca de forma exacta hasta tener esta cantidad de vectores
SEED = 42


@dataclass
class VectorStats:
    searches: int = 0
    vectors_compared: int = 0  # nodos visitados (HNSW) o vectores comparados (IVF)


@dataclass(frozen=True)
class VectorResult:
    matches: List[Tuple[object, float]]  # (RID, SIMILARITY_SCORE) de mayor a menor
    compared: int


@dataclass
class _Entries:
    """Relación entre los identificadores enteros de HNSW/IVF y los RIDs."""
    rid_of: Dict[int, object] = field(default_factory=dict)
    id_of: Dict[object, int] = field(default_factory=dict)
    path_of: Dict[int, str] = field(default_factory=dict)
    rids_by_path: Dict[str, Set[object]] = field(default_factory=dict)
    next_id: int = 0

    def add(self, rid, path) -> int:
        identifier = self.next_id
        self.next_id += 1
        self.rid_of[identifier], self.id_of[rid], self.path_of[identifier] = rid, identifier, path
        self.rids_by_path.setdefault(path, set()).add(rid)
        return identifier

    def remove(self, rid) -> Optional[int]:
        identifier = self.id_of.pop(rid, None)
        if identifier is None:
            return None
        del self.rid_of[identifier]
        path = self.path_of.pop(identifier)
        self.rids_by_path[path].discard(rid)
        if not self.rids_by_path[path]:
            del self.rids_by_path[path]
        return identifier


def similarity(metric: str, value: float) -> float:
    """SIMILARITY_SCORE a partir del valor que devuelve el índice."""
    return 1.0 / (1.0 + value) if metric == "euclidean" else value


class VectorIndex:
    def __init__(self, filepath: str, method: str, metric: str = "euclidean"):
        if method not in METHODS:
            raise ValueError(f"Método de índice vectorial no soportado: {method}")
        if metric not in METRICS:
            raise ValueError(f"Métrica no soportada: {metric}; usa euclidean, cosine o dot")
        self.filepath = filepath
        self.method = method
        self.metric = metric
        self.stats = VectorStats()
        self._schema = None
        self._field: Optional[str] = None
        self._reset()

    def _reset(self) -> None:
        self._entries = _Entries()
        self._vectors: Dict[int, np.ndarray] = {}  # vivos, por identificador
        self._deleted: Set[int] = set()            # marcas de HNSW
        self._hnsw: Optional[HNSWIndex] = None
        self._ivf: Optional[IVFIndex] = None
        self._trained_size = 0

    # ------------------------------------------------------------------
    # Parámetros visibles en EXPLAIN
    # ------------------------------------------------------------------

    @property
    def size(self) -> int:
        return len(self._vectors)

    @property
    def nlist(self) -> Optional[int]:
        return self._ivf.nlist if self._ivf is not None else None

    @property
    def nprobe(self) -> Optional[int]:
        return None if self._ivf is None else max(1, round(math.sqrt(self._ivf.nlist)))

    def describe(self) -> str:
        if self.method == "hnsw":
            return f"M: {HNSW_M}; ef_construction: {HNSW_EF_CONSTRUCTION}; ef_search: {HNSW_EF_SEARCH}"
        if self._ivf is None:
            return f"nlist: -; exact search until {MIN_TRAIN} vectors"
        return f"nlist: {self.nlist}; nprobe: {self.nprobe}"

    # ------------------------------------------------------------------
    # Contrato del catálogo
    # ------------------------------------------------------------------

    def _vector(self, path: str) -> Optional[np.ndarray]:
        vector = np.asarray(self._schema.vector(self._field, path), dtype=float)
        # El coseno no está definido para el vector nulo: esa fila no se indexa.
        if self.metric == "cosine" and not np.linalg.norm(vector):
            return None
        return vector

    def bulk_load_from_storage(self, storage, field_name: str, *, replace: bool = True) -> int:
        """Construye el índice con todas las filas de la tabla."""
        self._schema, self._field = storage.schema, field_name
        self._reset()
        position = storage.schema.fields.index(field_name)
        if storage.schema.types[position] not in ("image", "audio"):
            raise ValueError("Los índices HNSW e IVF requieren una columna IMAGE o AUDIO")
        for rid, record in storage.scan():
            vector = self._vector(record[field_name])
            if vector is not None:
                self._vectors[self._entries.add(rid, record[field_name])] = vector
        self._build()
        return self.size

    def _build(self) -> None:
        if self.method == "hnsw":
            self._hnsw = HNSWIndex(HNSW_M, HNSW_EF_CONSTRUCTION, metric=_INNER_METRIC[self.metric], seed=SEED)
            for identifier, vector in self._vectors.items():
                self._hnsw.insert(identifier, vector)
            self._deleted = set()
        else:
            self._train()

    def _train(self) -> None:
        if len(self._vectors) < MIN_TRAIN:
            self._ivf, self._trained_size = None, 0
            return
        nlist = max(1, round(math.sqrt(len(self._vectors))))
        ivf = IVFIndex(nlist, metric=_INNER_METRIC[self.metric], seed=SEED)
        ivf.train(self._vectors)
        self._ivf, self._trained_size = ivf, len(self._vectors)

    def insert(self, path: str, rid) -> None:
        if self._schema is None:
            raise ValueError("El índice vectorial debe construirse antes de insertar")
        vector = self._vector(path)
        if vector is None:
            return
        if rid in self._entries.id_of:
            self.delete(path, rid)
        identifier = self._entries.add(rid, path)
        self._vectors[identifier] = vector
        if self.method == "hnsw":
            self._hnsw.insert(identifier, vector)
        elif self._ivf is None or len(self._vectors) >= 2 * self._trained_size:
            self._train()
        else:
            self._ivf.insert(identifier, vector)

    def delete(self, path: str, rid) -> bool:
        identifier = self._entries.remove(rid)
        if identifier is None:
            return False
        del self._vectors[identifier]
        if self.method == "ivf":
            if self._ivf is not None:
                self._ivf.delete(identifier)
        else:
            self._deleted.add(identifier)
            if len(self._deleted) > len(self._vectors):
                self._build()
        return True

    def search(self, path: str) -> List[object]:
        """RIDs de las filas con esa ruta (igualdad sobre la columna)."""
        return list(self._entries.rids_by_path.get(path, ()))

    # ------------------------------------------------------------------
    # Búsqueda k-NN
    # ------------------------------------------------------------------

    def knn(self, query: Iterable[float], k: int) -> VectorResult:
        """k vecinos más similares a `query`, de mayor a menor SIMILARITY_SCORE."""
        if type(k) is not int or k < 1:
            raise ValueError("k debe ser un entero positivo")
        query = np.asarray(query, dtype=float)
        if self._vectors:
            dimension = len(next(iter(self._vectors.values())))
            if query.shape != (dimension,):
                raise ValueError(f"El vector de consulta tiene {query.size} dimensiones; el índice usa {dimension}")
        if self.metric == "cosine" and not np.linalg.norm(query):
            raise ValueError("El coseno no está definido para un vector de consulta nulo")
        if not self._vectors:
            found, compared = [], 0
        elif self.method == "hnsw":
            wanted = min(k + len(self._deleted), len(self._vectors) + len(self._deleted))
            result = self._hnsw.search(query, wanted, max(HNSW_EF_SEARCH, wanted))
            found = [(i, value) for i, value in result.matches if i not in self._deleted][:k]
            compared = result.nodes_visited
        elif self._ivf is None:
            found, compared = self._exact(query, k), len(self._vectors)
        else:
            # Si las listas revisadas no tienen k vectores, se revisan más hasta tenerlos.
            nprobe, compared = self.nprobe, 0
            while True:
                result = self._ivf.search(query, k, nprobe)
                compared += result.vectors_compared
                if len(result.matches) >= min(k, len(self._vectors)) or nprobe == self._ivf.nlist:
                    break
                nprobe = min(2 * nprobe, self._ivf.nlist)
            found = result.matches
        self.stats.searches += 1
        self.stats.vectors_compared += compared
        matches = [(self._entries.rid_of[i], similarity(self.metric, value)) for i, value in found]
        return VectorResult(matches, compared)

    def _exact(self, query: np.ndarray, k: int) -> List[Tuple[int, float]]:
        ids = list(self._vectors)
        data = np.asarray([self._vectors[i] for i in ids])
        if self.metric == "euclidean":
            values = np.linalg.norm(data - query, axis=1)
            order = sorted(range(len(ids)), key=lambda i: (values[i], ids[i]))
        else:
            values = data @ query
            if self.metric == "cosine":
                values = values / (np.linalg.norm(data, axis=1) * np.linalg.norm(query))
            order = sorted(range(len(ids)), key=lambda i: (-values[i], ids[i]))
        return [(ids[i], float(values[i])) for i in order[:k]]

    def reset_stats(self) -> None:
        self.stats = VectorStats()

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------

    def flush(self) -> None:
        if self._hnsw is not None:
            self._hnsw.save(self.filepath)
        elif self._ivf is not None:
            self._ivf.save(self.filepath)

    def close(self) -> None:
        self.flush()

    def __len__(self) -> int:
        return self.size
