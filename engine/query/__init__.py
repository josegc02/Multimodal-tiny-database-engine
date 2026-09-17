"""Procesamiento y optimización de consultas SQL."""

from engine.query.external_algorithms import (
    Aggregate, BufferConfig, ExecutionStats, OrderKey,
    external_hash_group_by, external_hash_join, external_sort,
)
from engine.query.planner import IndexInfo, Plan, QueryPlanner, TableStats
from engine.query.executor import QueryExecutor

__all__ = [
    "Aggregate", "BufferConfig", "ExecutionStats", "OrderKey",
    "external_hash_group_by", "external_hash_join", "external_sort",
    "IndexInfo", "Plan", "QueryPlanner", "TableStats", "QueryExecutor",
]
