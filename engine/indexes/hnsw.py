"""Índice HNSW para vectores densos."""

import heapq
import json
import random
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class HNSWSearchResult:
    matches: list[tuple[int, float]]
    nodes_visited: int


class HNSWIndex:
    """Grafo de vecinos por capas para búsqueda aproximada."""

    def __init__(self, M: int = 8, ef_construction: int = 50, *,
                 metric: str = "euclidean", seed: int = 0):
        if type(M) is not int or M < 2:
            raise ValueError("M debe ser un entero mayor o igual a 2")
        if type(ef_construction) is not int or ef_construction < M:
            raise ValueError("ef_construction debe ser un entero mayor o igual a M")
        if metric not in ("euclidean", "dot_product", "cosine"):
            raise ValueError("Métrica no soportada")
        self.M = M
        self.ef_construction = ef_construction
        self.metric = metric
        self.seed = seed
        self._rng = random.Random(seed)
        self.dimension: int | None = None
        self.vectors: dict[int, np.ndarray] = {}
        self.levels: dict[int, int] = {}
        self.links: dict[int, list[set[int]]] = {}
        # Cuántos enlaces llegan a cada nodo en cada capa: el recorte nunca borra el último.
        self.incoming: dict[int, list[int]] = {}
        self.entrypoint: int | None = None
        self.max_level = -1

    def _random_level(self) -> int:
        level = 0
        while self._rng.random() < 1 / self.M:
            level += 1
        return level

    def _validate_vector(self, vector: Sequence[float]) -> np.ndarray:
        result = np.asarray(vector, dtype=float)
        if result.ndim != 1 or len(result) == 0 or not np.isfinite(result).all():
            raise ValueError("El vector debe ser un arreglo 1D de números finitos")
        if self.dimension is not None and len(result) != self.dimension:
            raise ValueError("El vector debe tener la dimensión del índice")
        if self.metric == "cosine" and np.linalg.norm(result) == 0:
            raise ValueError("El coseno requiere vectores no nulos")
        return result

    def _distance(self, a: np.ndarray, b: np.ndarray) -> float:
        if self.metric == "euclidean":
            return float(np.linalg.norm(a - b))
        product = float(a @ b)
        if self.metric == "dot_product":
            return -product
        return -product / float(np.linalg.norm(a) * np.linalg.norm(b))

    def _distances_to(self, query: np.ndarray, identifiers: list[int]) -> list[float]:
        """Distancia de `query` a varios nodos con una sola operación matricial.

        Equivale a llamar _distance por cada nodo, pero evita el costo de numpy por
        llamada: la construcción calcula cientos de miles de distancias.
        """
        if not identifiers:
            return []
        matrix = np.stack([self.vectors[i] for i in identifiers])
        return self._distances(matrix, query[None, :])[:, 0].tolist()

    def _greedy(self, query: np.ndarray, entry: int, layer: int) -> tuple[int, set[int]]:
        current = entry
        visited = {entry}
        best = self._distance(query, self.vectors[entry])
        while True:
            next_node = current
            neighbors = sorted(self.links[current][layer])
            visited.update(neighbors)
            for neighbor, distance in zip(neighbors, self._distances_to(query, neighbors)):
                if (distance, neighbor) < (best, next_node):
                    best, next_node = distance, neighbor
            if next_node == current:
                return current, visited
            current = next_node

    def _search_layer(self, query: np.ndarray, entry: int, layer: int,
                      ef: int) -> tuple[list[tuple[float, int]], set[int]]:
        distance = self._distance(query, self.vectors[entry])
        candidates = [(distance, entry)]
        best = [(-distance, -entry)]
        visited = {entry}
        while candidates:
            current_distance, current = heapq.heappop(candidates)
            if len(best) == ef and (current_distance, current) > (-best[0][0], -best[0][1]):
                break
            pending = sorted(n for n in self.links[current][layer] if n not in visited)
            visited.update(pending)
            for neighbor, distance in zip(pending, self._distances_to(query, pending)):
                if len(best) < ef or (distance, neighbor) < (-best[0][0], -best[0][1]):
                    heapq.heappush(candidates, (distance, neighbor))
                    heapq.heappush(best, (-distance, -neighbor))
                    if len(best) > ef:
                        heapq.heappop(best)
        return sorted((-distance, -identifier) for distance, identifier in best), visited

    def max_links(self, layer: int) -> int:
        """Vecinos que guarda un nodo por capa: 2·M en la capa 0 y M en las demás (Malkov y Yashunin)."""
        return 2 * self.M if layer == 0 else self.M

    def _select_neighbors(self, base: np.ndarray, candidates: list[int], limit: int) -> list[int]:
        """Heurística de selección de vecinos (Malkov y Yashunin, algoritmo 4).

        Recorre los candidatos del más cercano al más lejano y acepta uno solo si
        está más cerca de `base` que de todos los ya aceptados. Así los vecinos
        apuntan en direcciones distintas y el grafo sigue conectado aunque los
        datos formen grupos; quedarse solo con los más cercanos ataba todos los
        enlaces a un mismo grupo.
        """
        if not candidates:
            return []
        matrix = np.stack([self.vectors[c] for c in candidates])
        to_base = self._distances(matrix, base[None, :])[:, 0]
        between = self._distances(matrix, matrix)
        order = sorted(range(len(candidates)), key=lambda i: (to_base[i], candidates[i]))
        chosen: list[int] = []
        for i in order:
            if len(chosen) == limit:
                break
            if all(to_base[i] < between[i, j] for j in chosen):
                chosen.append(i)
        return [candidates[i] for i in chosen]

    def _distances(self, a: np.ndarray, b: np.ndarray) -> np.ndarray:
        """Matriz de distancias entre las filas de `a` y las de `b`, con la misma métrica que _distance."""
        gram = a @ b.T
        if self.metric == "dot_product":
            return -gram
        if self.metric == "cosine":
            return -gram / np.outer(np.linalg.norm(a, axis=1), np.linalg.norm(b, axis=1))
        squared = np.einsum("ij,ij->i", a, a)[:, None] + np.einsum("ij,ij->i", b, b)[None, :] - 2 * gram
        return np.sqrt(np.maximum(squared, 0.0))

    def _prune(self, identifier: int, layer: int) -> None:
        """Deja en la lista de `identifier` a lo más max_links vecinos, elegidos con la heurística.

        Los enlaces son dirigidos: recortar la lista de un nodo no toca las listas
        de los demás. Si se borrara también el enlace de vuelta, un nodo podía
        perder todos sus vecinos y quedar inalcanzable para la búsqueda.

        Tampoco se borra el único enlace que llega a un vecino: sin él, ese vecino
        no tendría por dónde ser alcanzado. En ese caso la lista puede superar
        max_links.
        """
        neighbors = self.links[identifier][layer]
        limit = self.max_links(layer)
        if len(neighbors) <= limit:
            return
        kept = set(self._select_neighbors(self.vectors[identifier], list(neighbors), limit))
        for other in neighbors - kept:
            if self.incoming[other][layer] <= 1:
                kept.add(other)
            else:
                self.incoming[other][layer] -= 1
        self.links[identifier][layer] = kept

    def insert(self, identifier: int, vector: Sequence[float]) -> None:
        """Inserta un nodo y lo conecta con vecinos en cada capa que alcanza."""
        if type(identifier) is not int or identifier in self.vectors:
            raise ValueError("El identificador debe ser un entero nuevo")
        vector = self._validate_vector(vector)
        if self.dimension is None:
            self.dimension = len(vector)
        level = self._random_level()
        self.vectors[identifier] = vector.copy()
        self.levels[identifier] = level
        self.links[identifier] = [set() for _ in range(level + 1)]
        self.incoming[identifier] = [0] * (level + 1)
        if self.entrypoint is None:
            self.entrypoint, self.max_level = identifier, level
            return

        entry = self.entrypoint
        for layer in range(self.max_level, level, -1):
            entry, _ = self._greedy(vector, entry, layer)
        for layer in range(min(level, self.max_level), -1, -1):
            candidates, _ = self._search_layer(vector, entry, layer, self.ef_construction)
            chosen = self._select_neighbors(vector, [c for _, c in candidates], self.M)
            for neighbor in chosen:
                self.links[identifier][layer].add(neighbor)
                self.incoming[neighbor][layer] += 1
                self.links[neighbor][layer].add(identifier)
                self.incoming[identifier][layer] += 1
                self._prune(neighbor, layer)
            if candidates:
                entry = candidates[0][1]
        if level > self.max_level:
            self.entrypoint, self.max_level = identifier, level

    def search(self, query: Sequence[float], k: int = 10,
               ef_search: int = 50) -> HNSWSearchResult:
        """Busca k vecinos y cuenta los nodos distintos visitados."""
        if type(k) is not int or k < 1:
            raise ValueError("k debe ser un entero positivo")
        if type(ef_search) is not int or ef_search < k:
            raise ValueError("ef_search debe ser un entero mayor o igual a k")
        if self.entrypoint is None:
            return HNSWSearchResult([], 0)
        query = self._validate_vector(query)
        entry = self.entrypoint
        visited: set[int] = set()
        for layer in range(self.max_level, 0, -1):
            entry, layer_visited = self._greedy(query, entry, layer)
            visited.update(layer_visited)
        candidates, layer_visited = self._search_layer(query, entry, 0, ef_search)
        visited.update(layer_visited)
        sign = 1 if self.metric == "euclidean" else -1
        matches = [(identifier, sign * distance) for distance, identifier in candidates[:k]]
        return HNSWSearchResult(matches, len(visited))

    def save(self, path: str | Path) -> None:
        """Guarda el grafo y el estado aleatorio en JSON."""
        payload = {
            "version": 1,
            "M": self.M,
            "ef_construction": self.ef_construction,
            "metric": self.metric,
            "seed": self.seed,
            "dimension": self.dimension,
            "entrypoint": self.entrypoint,
            "max_level": self.max_level,
            "rng_state": self._rng.getstate(),
            "nodes": [
                [identifier, vector.tolist(), self.levels[identifier],
                 [sorted(neighbors) for neighbors in self.links[identifier]]]
                for identifier, vector in self.vectors.items()
            ],
        }
        Path(path).write_text(json.dumps(payload), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "HNSWIndex":
        """Carga un índice guardado con save."""
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if payload["version"] != 1:
            raise ValueError("Versión de índice no soportada")
        index = cls(payload["M"], payload["ef_construction"],
                    metric=payload["metric"], seed=payload["seed"])
        index.dimension = payload["dimension"]
        index.entrypoint = payload["entrypoint"]
        index.max_level = payload["max_level"]
        for identifier, vector, level, layers in payload["nodes"]:
            if identifier in index.vectors or len(layers) != level + 1:
                raise ValueError("Nodo inválido en el índice")
            index.vectors[identifier] = index._validate_vector(vector)
            index.levels[identifier] = level
            index.links[identifier] = [set(neighbors) for neighbors in layers]
            index.incoming[identifier] = [0] * len(layers)
        for identifier, layers in index.links.items():
            for layer, neighbors in enumerate(layers):
                # Los enlaces son dirigidos: basta con que el vecino exista en esa capa.
                if any(other not in index.links or layer >= len(index.links[other]) or other == identifier
                       for other in neighbors):
                    raise ValueError("Enlaces inválidos en el índice")
                for other in neighbors:
                    index.incoming[other][layer] += 1
        if (index.entrypoint is None) != (not index.vectors):
            raise ValueError("Punto de entrada inválido")
        if index.entrypoint is not None and index.entrypoint not in index.vectors:
            raise ValueError("Punto de entrada inválido")
        index._rng.setstate(cls._as_tuple(payload["rng_state"]))
        return index

    @staticmethod
    def _as_tuple(value):
        if isinstance(value, list):
            return tuple(HNSWIndex._as_tuple(item) for item in value)
        return value
