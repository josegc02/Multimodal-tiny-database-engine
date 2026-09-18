"""Selección de operadores físicos mediante costos aproximados de páginas.

Estos métodos reciben operaciones estructuradas desde el adaptador SQL.
Las estadísticas son estimaciones del catálogo, no se obtiene la
cardinalidad leyendo/materializando una tabla durante la planificación.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
import math
from typing import Any, Mapping, Sequence

from engine.query.external_algorithms import (
    Aggregate, BufferConfig, OrderKey, _aggregates, _fields, _key, _order_keys,
)


@dataclass(frozen=True)
class TableStats:
    rows: int
    pages: int
    distinct_values: Mapping[str, int] = dataclass_field(default_factory=dict)

    def __post_init__(self):
        if (type(self.rows) is not int or self.rows < 0
                or type(self.pages) is not int or self.pages < 0
                or (self.rows > 0 and self.pages == 0)):
            raise ValueError("Cardinalidad y páginas deben ser enteros no negativos coherentes")
        if any(type(n) is not int or n < 0 or n > self.rows or (self.rows and not n)
               for n in self.distinct_values.values()):
            raise ValueError("Cantidad de valores distintos inválida")


@dataclass(frozen=True)
class IndexInfo:
    """Índice de un campo; valid indica que refleja el storage actual.

    Igualdad requiere search(key) -> iterable de RIDs. Orden requiere ordered=True
    e iter_ordered(reverse=False) -> RIDs de TODOS los registros, con duplicados.
    nulls_first_ascending describe la posición de NULL del recorrido ascendente.
    El hash existente solo ofrece igualdad; el B+ incompleto no se selecciona.
    """

    name: str
    field: str
    index: Any
    ordered: bool = False
    clustered: bool = False
    valid: bool = True
    lookup_pages: float = 1.0
    nulls_first_ascending: bool = False

    def __post_init__(self):
        if not self.name or not self.field or not math.isfinite(self.lookup_pages) or self.lookup_pages < 0:
            raise ValueError("Metadatos de índice inválidos")

    @property
    def supports_equality(self) -> bool:
        return self.valid and callable(getattr(self.index, "search", None))

    @property
    def supports_order(self) -> bool:
        return self.valid and self.ordered and callable(getattr(self.index, "iter_ordered", None))


@dataclass(frozen=True)
class Plan:
    operation: str
    algorithm: str
    estimated_io: float
    reason: str
    config: BufferConfig
    index: IndexInfo | None = None
    order_by: tuple[OrderKey, ...] = ()
    group_by: tuple[str, ...] = ()
    aggregates: Mapping[str, Aggregate] = dataclass_field(default_factory=dict)
    left_on: tuple[str, ...] = ()
    right_on: tuple[str, ...] = ()
    field: str | None = None
    value: Any = None
    reverse: bool = False

    def explain(self) -> dict:
        return {
            "operation": self.operation,
            "algorithm": self.algorithm,
            "estimated_io": self.estimated_io,
            "reason": self.reason,
            "index": self.index.name if self.index is not None else None,
            "buffer_pages": self.config.buffer_pages,
            "records_per_page": self.config.records_per_page,
        }


class QueryPlanner:
    """Compara I/O secuencial con accesos por índice, penalizando lecturas dispersas.

    Sin estadísticas de valores distintos se asume baja selectividad (un valor).
    Los costos no garantizan el tiempo real ni predicen skew. Un índice hash no
    satisface ORDER BY; GROUP BY puede consumir un recorrido ordenado de un índice.
    En caso de empate se conserva el operador externo/secuencial.
    """

    def __init__(self, config: BufferConfig | None = None, *, random_page_cost: float = 4.0):
        if not math.isfinite(random_page_cost) or random_page_cost < 1:
            raise ValueError("random_page_cost debe ser finito y al menos 1")
        self.config = config or BufferConfig()
        self.random_page_cost = random_page_cost

    def _plan(self, operation, algorithm, cost, reason, **kwargs):
        return Plan(operation, algorithm, float(cost), reason, self.config, **kwargs)

    def _sort_cost(self, stats: TableStats) -> float:
        runs = max(1, math.ceil(stats.rows / self.config.capacity))
        passes = 0
        while runs > 1:
            runs = math.ceil(runs / self.config.fan_in)
            passes += 1
        # Lectura inicial, escritura de runs, mezclas y lectura del run final.
        return stats.pages * (3 + 2 * passes)

    def _hash_cost(self, pages: int, build_records: int) -> float:
        cost = 3 * pages  # Particionar (leer/escribir) y construir/sondear (leer).
        per_partition = math.ceil(build_records / self.config.fan_in)
        for _ in range(self.config.max_partition_depth):
            if per_partition <= self.config.hash_capacity:
                break
            cost += 2 * pages
            per_partition = math.ceil(per_partition / self.config.fan_in)
        return cost

    def _fetch_cost(self, stats: TableStats, index: IndexInfo, matches: float) -> float:
        if index.clustered:
            return min(stats.pages, math.ceil(matches / self.config.records_per_page))
        return matches * self.random_page_cost

    @staticmethod
    def _matches(stats: TableStats, field: str) -> float:
        return stats.rows / max(1, stats.distinct_values.get(field, 1))

    def plan_order_by(self, stats: TableStats, order_by: str | Sequence[str | OrderKey],
                      indexes: Sequence[IndexInfo] = ()) -> Plan:
        order = _order_keys(order_by)
        plan = self._plan("order_by", "external_sort", self._sort_cost(stats),
                          "Runs y mezcla k-way; no hay un recorrido ordenado de menor costo.", order_by=order)
        for index in indexes:
            if not index.supports_order or len(order) != 1 or index.field != order[0].field:
                continue
            rule = order[0]
            nulls_first = index.nulls_first_ascending != rule.descending
            if nulls_first != rule.nulls_first:
                continue
            cost = index.lookup_pages + self._fetch_cost(stats, index, stats.rows)
            if cost < plan.estimated_io:
                plan = self._plan("order_by", "index_order_scan", cost,
                                  "El índice ofrece el orden y NULLs requeridos con menor I/O.",
                                  index=index, order_by=order, reverse=rule.descending)
        return plan

    def plan_group_by(self, stats: TableStats, group_by: str | Sequence[str],
                      aggregates: Mapping[str, Aggregate] | None = None,
                      indexes: Sequence[IndexInfo] = ()) -> Plan:
        fields = _fields(group_by, allow_empty=True)
        specs = _aggregates(fields, aggregates)
        groups = min(stats.rows, math.prod(stats.distinct_values.get(f, stats.rows) for f in fields))
        cost = self._hash_cost(stats.pages, groups) if fields else stats.pages
        plan = self._plan("group_by", "external_hash_group_by", cost,
                          "Particiones en disco y agregación acotada; sin recorrido ordenado más barato.",
                          group_by=fields, aggregates=specs)
        for index in indexes:
            if not index.supports_order or fields != (index.field,):
                continue
            cost = index.lookup_pages + self._fetch_cost(stats, index, stats.rows)
            if cost < plan.estimated_io:
                plan = self._plan("group_by", "index_group_by", cost,
                                  "Claves contiguas del índice permiten acumular un grupo a la vez.",
                                  index=index, group_by=fields, aggregates=specs)
        return plan

    def plan_join(self, left: TableStats, right: TableStats,
                  left_on: str | Sequence[str], right_on: str | Sequence[str],
                  right_indexes: Sequence[IndexInfo] = ()) -> Plan:
        lfields, rfields = _fields(left_on), _fields(right_on)
        if len(lfields) != len(rfields):
            raise ValueError("JOIN requiere igual cantidad de campos en ambos lados")
        cost = self._hash_cost(left.pages + right.pages, min(left.rows, right.rows))
        plan = self._plan("join", "external_hash_join", cost,
                          "Particionar ambas relaciones evita búsquedas aleatorias por cada fila izquierda.",
                          left_on=lfields, right_on=rfields)
        for index in right_indexes:
            if not index.supports_equality or rfields != (index.field,):
                continue
            matches = self._matches(right, index.field)
            cost = left.pages + left.rows * (index.lookup_pages + self._fetch_cost(right, index, matches))
            if cost < plan.estimated_io:
                plan = self._plan("join", "index_nested_loop_join", cost,
                                  "El lado izquierdo reducido hace más barato sondear el índice derecho.",
                                  index=index, left_on=lfields, right_on=rfields)
        return plan

    def plan_equality(self, stats: TableStats, field: str, value: Any,
                      indexes: Sequence[IndexInfo] = ()) -> Plan:
        _fields(field)
        _key({field: value}, (field,))
        plan = self._plan("equality", "sequential_scan", stats.pages,
                          "El scan secuencial cuesta menos o no hay índice de igualdad vigente.",
                          field=field, value=value)
        for index in indexes:
            if value is None or not index.supports_equality or index.field != field:
                continue
            cost = index.lookup_pages + self._fetch_cost(stats, index, self._matches(stats, field))
            if cost < plan.estimated_io:
                plan = self._plan("equality", "index_scan", cost,
                                  "La selectividad estimada reduce las lecturas usando el índice.",
                                  index=index, field=field, value=value)
        return plan
