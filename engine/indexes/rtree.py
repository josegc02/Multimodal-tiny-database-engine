"""R-Tree en disco para puntos 2D (Guttman, 1984) con split cuadrático.

Cada nodo ocupa una página de 4096 B. Las entradas son (rectángulo, valor):
en una hoja el rectángulo es el punto y el valor su RID; en un nodo interno el
rectángulo es el MBR del hijo y el valor su número de página. Por velocidad,
dentro del árbol los rectángulos son tuplas (min_lat, min_lon, max_lat, max_lon)
y los RID tuplas (página, slot, archivo); la API recibe y devuelve Point, MBR y RID.

Página 0: cabecera. Las páginas liberadas al eliminar forman una lista enlazada
y se reutilizan.
"""

from __future__ import annotations

import math
import heapq
import os
import struct
from dataclasses import dataclass, field
from typing import Iterable, Iterator, List, Optional, Tuple

from engine.spatial.distance import Metric, distance, mindist, radius_to_mbr
from engine.spatial.geometry import MBR, Point, Polygon
from engine.storage.record import RID

PAGE_SIZE = 4096
MAGIC = b"RTR1"
NO_PAGE = 0  # la página 0 es la cabecera, así que nunca es un nodo

# magic, raíz, altura, entradas, páginas, primera libre, M hoja, M interno
HEADER = struct.Struct(">4sIIIIIII")
NODE_HEADER = struct.Struct(">BH")            # nivel (0 = hoja), cantidad de entradas
LEAF_ENTRY = struct.Struct(">ddIHB")          # lat, lon, RID (página, slot, archivo)
INTERNAL_ENTRY = struct.Struct(">ddddI")      # MBR del hijo, página del hijo
FREE_LINK = struct.Struct(">I")

MAX_LEAF = (PAGE_SIZE - NODE_HEADER.size) // LEAF_ENTRY.size              # 177
MAX_INTERNAL = (PAGE_SIZE - NODE_HEADER.size) // INTERNAL_ENTRY.size      # 113
MIN_FILL = 0.4
RID_FILES = ("main", "aux")

Box = Tuple[float, float, float, float]


def _area(b: Box) -> float:
    return (b[2] - b[0]) * (b[3] - b[1])


def _margin(b: Box) -> float:
    return (b[2] - b[0]) + (b[3] - b[1])


def _union(a: Box, b: Box) -> Box:
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def _union_all(boxes: Iterable[Box]) -> Box:
    boxes = list(boxes)
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def _growth(box: Box, add: Box) -> Tuple[float, float]:
    """Crecimiento de área (y de semiperímetro, para desempatar puntos alineados)."""
    height = max(box[2], add[2]) - min(box[0], add[0])
    width = max(box[3], add[3]) - min(box[1], add[1])
    old_height, old_width = box[2] - box[0], box[3] - box[1]
    return height * width - old_height * old_width, height + width - old_height - old_width


def _intersects(a: Box, b: Box) -> bool:
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def _contains(outer: Box, inner: Box) -> bool:
    return outer[0] <= inner[0] and outer[1] <= inner[1] and inner[2] <= outer[2] and inner[3] <= outer[3]


def _rid_key(rid: RID) -> Tuple[int, int, int]:
    return rid.page_id, rid.slot_id, RID_FILES.index(rid.file)


def _rid(key: Tuple[int, int, int]) -> RID:
    return RID(key[0], key[1], RID_FILES[key[2]])


def _box_of(mbr: MBR) -> Box:
    return (mbr.min_lat, mbr.min_lon, mbr.max_lat, mbr.max_lon)


def _point_box(point: Point) -> Box:
    return (point.lat, point.lon, point.lat, point.lon)


@dataclass
class RTreeStats:
    """Contadores de la última consulta (EXPLAIN ANALYZE y benchmarks)."""

    nodes_visited: int = 0
    leaves_visited: int = 0
    candidates: int = 0
    refined: int = 0
    results: int = 0


@dataclass
class RTreeNode:
    page_id: int
    level: int                                  # 0 = hoja
    entries: List[Tuple[Box, object]] = field(default_factory=list)

    @property
    def is_leaf(self) -> bool:
        return self.level == 0

    def box(self) -> Box:
        return _union_all(b for b, _ in self.entries)


class RTree:
    """R-Tree persistente. `max_entries` fija M en hojas y nodos internos (para pruebas)."""

    def __init__(self, filepath: str, max_entries: Optional[int] = None):
        if max_entries is not None and (type(max_entries) is not int
                                        or not 3 <= max_entries <= min(MAX_LEAF, MAX_INTERNAL)):
            raise ValueError(f"max_entries debe estar entre 3 y {min(MAX_LEAF, MAX_INTERNAL)}")
        self.filepath = os.fspath(filepath)
        self.last_stats = RTreeStats()
        exists = os.path.exists(self.filepath) and os.path.getsize(self.filepath) > 0
        self._fh = open(self.filepath, "r+b" if exists else "w+b")
        try:
            if exists:
                self._read_header()
                if max_entries is not None and (self.max_leaf, self.max_internal) != (max_entries, max_entries):
                    raise ValueError("max_entries no coincide con el del archivo")
            else:
                self.max_leaf = max_entries or MAX_LEAF
                self.max_internal = max_entries or MAX_INTERNAL
                self._reset()
        except Exception:
            self._fh.close()
            raise

    # --- Archivo -----------------------------------------------------------------

    def _read_header(self) -> None:
        self._fh.seek(0)
        data = self._fh.read(HEADER.size)
        if len(data) != HEADER.size or data[:4] != MAGIC:
            raise ValueError(f"{self.filepath} no es un archivo R-Tree")
        (_, self.root, self.height, self.size, self.page_count,
         self.free_head, self.max_leaf, self.max_internal) = HEADER.unpack(data)

    def _write_header(self) -> None:
        self._fh.seek(0)
        self._fh.write(HEADER.pack(MAGIC, self.root, self.height, self.size, self.page_count,
                                   self.free_head, self.max_leaf, self.max_internal).ljust(PAGE_SIZE, b"\0"))

    def _reset(self) -> None:
        self._fh.truncate(0)
        self.root, self.height, self.size, self.page_count, self.free_head = 1, 1, 0, 2, NO_PAGE
        self._write_header()
        self._write_node(RTreeNode(self.root, 0))

    def _read_node(self, page_id: int) -> RTreeNode:
        self._fh.seek(page_id * PAGE_SIZE)
        data = self._fh.read(PAGE_SIZE)
        level, count = NODE_HEADER.unpack_from(data)
        node = RTreeNode(page_id, level)
        offset = NODE_HEADER.size
        if level == 0:
            for _ in range(count):
                lat, lon, page, slot, file = LEAF_ENTRY.unpack_from(data, offset)
                node.entries.append(((lat, lon, lat, lon), (page, slot, file)))
                offset += LEAF_ENTRY.size
        else:
            for _ in range(count):
                *box, child = INTERNAL_ENTRY.unpack_from(data, offset)
                node.entries.append((tuple(box), child))
                offset += INTERNAL_ENTRY.size
        return node

    def _write_node(self, node: RTreeNode) -> None:
        parts = [NODE_HEADER.pack(node.level, len(node.entries))]
        if node.is_leaf:
            parts += [LEAF_ENTRY.pack(box[0], box[1], *rid) for box, rid in node.entries]
        else:
            parts += [INTERNAL_ENTRY.pack(*box, child) for box, child in node.entries]
        self._fh.seek(node.page_id * PAGE_SIZE)
        self._fh.write(b"".join(parts).ljust(PAGE_SIZE, b"\0"))

    def _allocate(self) -> int:
        if self.free_head != NO_PAGE:
            page_id = self.free_head
            self._fh.seek(page_id * PAGE_SIZE)
            self.free_head = FREE_LINK.unpack(self._fh.read(FREE_LINK.size))[0]
            return page_id
        self.page_count += 1
        return self.page_count - 1

    def _free(self, page_id: int) -> None:
        self._fh.seek(page_id * PAGE_SIZE)
        self._fh.write(FREE_LINK.pack(self.free_head).ljust(PAGE_SIZE, b"\0"))
        self.free_head = page_id

    def _capacity(self, node: RTreeNode) -> int:
        return self.max_leaf if node.is_leaf else self.max_internal

    def _min_entries(self, node: RTreeNode) -> int:
        return max(1, math.ceil(MIN_FILL * self._capacity(node)))

    # --- Inserción -----------------------------------------------------------------

    def insert(self, key: Point, rid: RID) -> None:
        self._check_entry(key, rid)
        self._insert_entry((_point_box(key), _rid_key(rid)), level=0)
        self.size += 1
        self._write_header()

    @staticmethod
    def _check_entry(key, rid) -> None:
        if not isinstance(key, Point):
            raise TypeError(f"Se esperaba un Point: {key!r}")
        if not isinstance(rid, RID) or rid.file not in RID_FILES:
            raise TypeError(f"Se esperaba un RID de 'main' o 'aux': {rid!r}")

    def _insert_entry(self, entry: Tuple[Box, object], level: int) -> None:
        """Agrega la entrada en un nodo del nivel indicado (0 = hoja)."""
        path, indexes = self._choose_path(entry[0], level)
        node = path[-1]
        node.entries.append(entry)
        sibling = self._split(node) if len(node.entries) > self._capacity(node) else None
        self._write_node(node)

        for parent, child, index in zip(reversed(path[:-1]), reversed(path[1:]), reversed(indexes)):
            old_box = parent.entries[index][0]
            if sibling is None:
                # Sin split debajo, el hijo solo creció lo necesario para la entrada nueva.
                new_box = _union(old_box, entry[0])
                if new_box == old_box:
                    return  # nada cambia de aquí hacia arriba
                parent.entries[index] = (new_box, child.page_id)
            else:
                parent.entries[index] = (child.box(), child.page_id)
                parent.entries.append((sibling.box(), sibling.page_id))
            sibling = self._split(parent) if len(parent.entries) > self._capacity(parent) else None
            self._write_node(parent)

        if sibling is not None:  # se dividió la raíz: el árbol crece un nivel
            old_root = path[0]
            root = RTreeNode(self._allocate(), old_root.level + 1,
                             [(old_root.box(), old_root.page_id), (sibling.box(), sibling.page_id)])
            self._write_node(root)
            self.root, self.height = root.page_id, self.height + 1

    def _choose_path(self, box: Box, level: int) -> Tuple[List[RTreeNode], List[int]]:
        """ChooseLeaf: baja por el hijo que menos crece (desempate: menor área).

        Devuelve los nodos del camino y, para cada uno, la posición del hijo elegido.
        """
        node = self._read_node(self.root)
        path, indexes = [node], []
        while node.level > level:
            index = min(range(len(node.entries)),
                        key=lambda i: (_growth(node.entries[i][0], box), _area(node.entries[i][0])))
            indexes.append(index)
            node = self._read_node(node.entries[index][1])
            path.append(node)
        return path, indexes

    def _split(self, node: RTreeNode) -> RTreeNode:
        """Split cuadrático: reparte las entradas entre `node` y un nodo nuevo, que devuelve."""
        entries, minimum = node.entries, self._min_entries(node)
        boxes = [b for b, _ in entries]
        areas = [_area(b) for b in boxes]
        margins = [_margin(b) for b in boxes]

        # Semillas: el par que más área desperdicia si quedara en el mismo nodo
        # (desempate por semiperímetro, para puntos alineados con área 0).
        best, seeds = None, (0, 1)
        for i, a in enumerate(boxes):
            for j in range(i + 1, len(boxes)):
                b = boxes[j]
                height = max(a[2], b[2]) - min(a[0], b[0])
                width = max(a[3], b[3]) - min(a[1], b[1])
                waste = (height * width - areas[i] - areas[j], height + width - margins[i] - margins[j])
                if best is None or waste > best:
                    best, seeds = waste, (i, j)

        groups = [[entries[seeds[0]]], [entries[seeds[1]]]]
        group_boxes = [boxes[seeds[0]], boxes[seeds[1]]]
        rest = [e for k, e in enumerate(entries) if k not in seeds]

        while rest:
            # Si un grupo necesita todas las restantes para llegar al mínimo, se las lleva.
            needy = next((g for g in (0, 1) if len(groups[g]) + len(rest) == minimum), None)
            if needy is not None:
                groups[needy] += rest
                group_boxes[needy] = _union_all([group_boxes[needy]] + [b for b, _ in rest])
                break
            # PickNext: la entrada con mayor diferencia de crecimiento entre los grupos.
            (a0, a1), (b0, b1) = (_area(x) for x in group_boxes), group_boxes
            m0, m1 = _margin(b0), _margin(b1)
            best, chosen = (-1.0, -1.0), 0
            for k, (b, _) in enumerate(rest):
                h0 = max(b0[2], b[2]) - min(b0[0], b[0])
                w0 = max(b0[3], b[3]) - min(b0[1], b[1])
                h1 = max(b1[2], b[2]) - min(b1[0], b[0])
                w1 = max(b1[3], b[3]) - min(b1[1], b[1])
                preference = (abs((h0 * w0 - a0) - (h1 * w1 - a1)), abs((h0 + w0 - m0) - (h1 + w1 - m1)))
                if preference > best:
                    best, chosen = preference, k
            entry = rest.pop(chosen)
            g = min((0, 1), key=lambda g: (_growth(group_boxes[g], entry[0]), _area(group_boxes[g]), len(groups[g])))
            groups[g].append(entry)
            group_boxes[g] = _union(group_boxes[g], entry[0])

        node.entries = groups[0]
        sibling = RTreeNode(self._allocate(), node.level, groups[1])
        self._write_node(sibling)
        return sibling

    def bulk_load(self, entries: Iterable[Tuple[Point, RID]]) -> int:
        """Inserta los pares uno por uno; devuelve cuántos se agregaron."""
        count = 0
        for key, rid in entries:
            self.insert(key, rid)
            count += 1
        return count

    def bulk_load_from_storage(self, storage, key_field: str, *, replace: bool = True) -> int:
        """Indexa la columna `key_field` (Point o tupla (lat, lon)) de un storage."""
        if key_field not in storage.schema.fields:
            raise ValueError(f"El campo '{key_field}' no existe en el schema")
        if replace:
            self._reset()
        values = ((value if isinstance(value, Point) else Point(*value), rid)
                  for rid, value in ((rid, record[key_field]) for rid, record in storage.scan()))
        return self.bulk_load(values)

    # --- Eliminación ---------------------------------------------------------------

    def delete(self, key: Point, rid: RID) -> bool:
        """Elimina el par (punto, RID); devuelve False si no estaba."""
        self._check_entry(key, rid)
        entry = (_point_box(key), _rid_key(rid))
        path = self._find_leaf(self._read_node(self.root), entry)
        if path is None:
            return False
        path[-1].entries.remove(entry)
        self._condense(path)
        self.size -= 1
        self._write_header()
        return True

    def _find_leaf(self, node: RTreeNode, entry: Tuple[Box, tuple]) -> Optional[List[RTreeNode]]:
        if node.is_leaf:
            return [node] if entry in node.entries else None
        for child_box, child in node.entries:
            if _contains(child_box, entry[0]):
                found = self._find_leaf(self._read_node(child), entry)
                if found is not None:
                    return [node] + found
        return None

    def _condense(self, path: List[RTreeNode]) -> None:
        """CondenseTree: quita los nodos con menos de m entradas y reinserta su contenido."""
        orphans = []  # (nivel, entradas)
        for parent, node in zip(reversed(path[:-1]), reversed(path[1:])):
            index = next(i for i, (_, page) in enumerate(parent.entries) if page == node.page_id)
            if len(node.entries) < self._min_entries(node):
                del parent.entries[index]
                orphans.append((node.level, node.entries))
                self._free(node.page_id)
            else:
                parent.entries[index] = (node.box(), node.page_id)
                self._write_node(node)
        root = path[0]
        if not root.is_leaf and not root.entries:
            root = RTreeNode(root.page_id, 0)
            self.height = 1
        self._write_node(root)

        # Una raíz interna con un solo hijo sobra: el hijo pasa a ser la raíz.
        while not root.is_leaf and len(root.entries) == 1:
            self._free(root.page_id)
            root = self._read_node(root.entries[0][1])
            self.root, self.height = root.page_id, self.height - 1

        for level, entries in sorted(orphans, key=lambda item: -item[0]):
            for entry in entries:
                self._reinsert(entry, level)

    def _reinsert(self, entry: Tuple[Box, object], level: int) -> None:
        """Reinserta en su nivel; si el árbol ya es más bajo, baja hasta los puntos."""
        if level <= self.height - 1:
            self._insert_entry(entry, level)
            return
        node = self._read_node(entry[1])
        self._free(node.page_id)
        for child in node.entries:
            self._reinsert(child, node.level)

    # --- Consultas -----------------------------------------------------------------

    def search_mbr(self, window: MBR) -> List[Tuple[Point, RID]]:
        """Puntos dentro del rectángulo (incluye el borde)."""
        box = _box_of(window)
        stats = self.last_stats = RTreeStats()
        results = []
        stack = [self.root]
        while stack:
            node = self._read_node(stack.pop())
            stats.nodes_visited += 1
            if node.is_leaf:
                stats.leaves_visited += 1
                for b, rid in node.entries:
                    stats.candidates += 1
                    if _contains(box, b):
                        results.append((Point(b[0], b[1]), _rid(rid)))
            else:
                stack.extend(child for b, child in node.entries if _intersects(box, b))
        stats.results = len(results)
        return results

    def search(self, key: Point) -> List[RID]:
        """RIDs guardados exactamente en ese punto."""
        return [rid for _, rid in self.search_mbr(MBR.from_point(key))]

    def range_query(self, center: Point, radius_m: float,
                    metric: Metric = Metric.HAVERSINE) -> List[Tuple[Point, RID, float]]:
        """Radio inclusivo en metros: MBR conservador y refinamiento exacto.

        Orden determinista por distancia y RID. `candidates` cuenta entradas de
        hojas inspeccionadas; `refined` cuenta distancias calculadas tras el MBR.
        """
        if not isinstance(center, Point):
            raise TypeError("El centro debe ser un Point")
        window = radius_to_mbr(center, radius_m, metric)
        candidates = self.search_mbr(window)
        results = []
        for point, rid in candidates:
            self.last_stats.refined += 1
            meters = distance(center, point, metric)
            if meters <= radius_m:
                results.append((point, rid, meters))
        results.sort(key=lambda row: (row[2], _rid_key(row[1])))
        self.last_stats.results = len(results)
        return results

    def knn(self, center: Point, k: int, metric: Metric = Metric.HAVERSINE) -> List[Tuple[Point, RID, float]]:
        """Best-first con MINDIST; empates por RID, sin descartar nodos empatados.

        La frontera contiene nodos y el heap de respuestas a lo sumo k puntos.
        El margen de poda (un micrómetro) protege las cotas del redondeo flotante;
        el orden final usa las distancias exactas, sin tolerancia.
        """
        if not isinstance(center, Point):
            raise TypeError("El centro debe ser un Point")
        if type(k) is not int or k < 0:
            raise ValueError("k debe ser un entero no negativo")
        distance(center, center, metric)  # valida incluso en un árbol vacío
        stats = self.last_stats = RTreeStats()
        if not k or not self.size:
            return []
        frontier, best = [(0.0, self.root)], []
        serial = 0
        while frontier:
            bound, page = heapq.heappop(frontier)
            if len(best) == k and bound > -best[0][0] + 1e-6:
                break
            node = self._read_node(page)
            stats.nodes_visited += 1
            if node.is_leaf:
                stats.leaves_visited += 1
                for box, rid_key in node.entries:
                    stats.candidates += 1
                    stats.refined += 1
                    point, rid = Point(box[0], box[1]), _rid(rid_key)
                    meters = distance(center, point, metric)
                    serial += 1
                    candidate = (-meters, tuple(-n for n in rid_key), serial, point, rid)
                    if len(best) < k:
                        heapq.heappush(best, candidate)
                    elif candidate[:2] > best[0][:2]:
                        heapq.heapreplace(best, candidate)
            else:
                for box, child in node.entries:
                    lower = mindist(center, MBR(*box), metric)
                    if len(best) < k or lower <= -best[0][0] + 1e-6:
                        heapq.heappush(frontier, (lower, child))
        results = [(point, rid, -negative) for negative, _, _, point, rid in best]
        results.sort(key=lambda row: (row[2], _rid_key(row[1])))
        stats.results = len(results)
        return results

    def within_polygon(self, polygon: Polygon) -> List[Tuple[Point, RID]]:
        """Filtro MBR y ray casting, incluyendo puntos sobre el borde."""
        if not isinstance(polygon, Polygon):
            raise TypeError("Se esperaba un Polygon")
        candidates = self.search_mbr(polygon.mbr())
        results = []
        for point, rid in candidates:
            self.last_stats.refined += 1
            if polygon.contains(point):
                results.append((point, rid))
        results.sort(key=lambda row: _rid_key(row[1]))
        self.last_stats.results = len(results)
        return results

    # --- Información y ciclo de vida -----------------------------------------------

    def __len__(self) -> int:
        return self.size

    def __iter__(self) -> Iterator[Tuple[Point, RID]]:
        for node in self._nodes():
            if node.is_leaf:
                for b, rid in node.entries:
                    yield Point(b[0], b[1]), _rid(rid)

    def _nodes(self) -> Iterator[RTreeNode]:
        stack = [self.root]
        while stack:
            node = self._read_node(stack.pop())
            yield node
            if not node.is_leaf:
                stack.extend(child for _, child in node.entries)

    def stats(self) -> dict:
        nodes = list(self._nodes())
        leaves = [n for n in nodes if n.is_leaf]
        return {
            "height": self.height,
            "entries": self.size,
            "nodes": len(nodes),
            "leaves": len(leaves),
            "max_leaf_entries": self.max_leaf,
            "max_internal_entries": self.max_internal,
            "leaf_fill": (sum(len(n.entries) for n in leaves) / (len(leaves) * self.max_leaf)) if leaves else 0.0,
            "file_bytes": self.page_count * PAGE_SIZE,
        }

    def flush(self) -> None:
        self._write_header()
        self._fh.flush()

    def close(self) -> None:
        if not self._fh.closed:
            self.flush()
            self._fh.close()

    def __enter__(self) -> RTree:
        return self

    def __exit__(self, *exc) -> None:
        self.close()
