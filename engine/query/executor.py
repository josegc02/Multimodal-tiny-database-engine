"""Ejecución incremental de planes físicos sobre HeapFile/SequentialFile.

El propietario del storage mantiene abiertos los archivos durante el recorrido.
Los índices deben estar sincronizados y pertenecer al campo/tabla declarados. Su
memoria (incluidas listas devueltas por search) es independiente del buffer de los
algoritmos externos. Cerrar el resultado si se interrumpe su consumo.
"""

from __future__ import annotations

from typing import Iterator

from engine.query.external_algorithms import (
    ExecutionStats, _key, external_hash_group_by, external_hash_join,
    external_sort, streaming_group_by,
)
from engine.query.planner import Plan


def _scan(storage):
    for _, record in storage.scan():
        yield record


def _index_rows(storage, index, *, reverse=False):
    for rid in index.iter_ordered(reverse=reverse):
        record = storage.get(rid)
        if record is not None:
            yield record


class QueryExecutor:
    def execute(self, plan: Plan, storage, right_storage=None, *, stats: ExecutionStats | None = None) -> Iterator:
        """Devuelve registros; JOIN devuelve pares (izquierdo, derecho).

        El plan incluye el buffer configurado en QueryPlanner. explain() permite
        mostrar el algoritmo, costo y motivo sin ejecutar la consulta.
        """
        stats = stats if stats is not None else ExecutionStats()
        if plan.index is not None and not plan.index.valid:
            raise ValueError("El índice del plan está marcado como obsoleto")
        if plan.algorithm == "external_sort":
            yield from external_sort(_scan(storage), plan.order_by, config=plan.config, stats=stats)
        elif plan.algorithm == "index_order_scan":
            yield from _index_rows(storage, plan.index.index, reverse=plan.reverse)
        elif plan.algorithm == "external_hash_group_by":
            yield from external_hash_group_by(_scan(storage), plan.group_by, plan.aggregates,
                                              config=plan.config, stats=stats)
        elif plan.algorithm == "index_group_by":
            yield from streaming_group_by(_index_rows(storage, plan.index.index),
                                          plan.group_by, plan.aggregates)
        elif plan.algorithm in {"external_hash_join", "index_nested_loop_join"}:
            if right_storage is None:
                raise ValueError("JOIN requiere el storage derecho")
            if plan.algorithm == "external_hash_join":
                yield from external_hash_join(_scan(storage), _scan(right_storage), plan.left_on,
                                              plan.right_on, config=plan.config, stats=stats)
            else:
                for left in _scan(storage):
                    key = _key(left, plan.left_on)
                    if any(value is None for value in key):
                        continue
                    stats.index_probes += 1
                    for rid in plan.index.index.search(key[0]):
                        right = right_storage.get(rid)
                        if right is not None and _key(right, plan.right_on) == key:
                            yield left, right
        elif plan.algorithm in {"index_scan", "sequential_scan"}:
            # Semántica de SQL '=': NULL no es igual ni siquiera a NULL.
            if plan.value is None:
                return
            if plan.algorithm == "index_scan":
                stats.index_probes += 1
                for rid in plan.index.index.search(plan.value):
                    record = storage.get(rid)
                    if record is not None and record[plan.field] == plan.value:
                        yield record
            else:
                for record in _scan(storage):
                    if record[plan.field] == plan.value:
                        yield record
        else:
            raise ValueError(f"Algoritmo de ejecución desconocido: {plan.algorithm}")
