"""Procesamiento y optimización de consultas SQL."""

from engine.query.external_algorithms import (
    Aggregate, BufferConfig, ExecutionStats, OrderKey,
    external_hash_group_by, external_hash_join, external_sort,
)
from engine.query.planner import IndexInfo, Plan, QueryPlanner, TableStats
from engine.query.executor import QueryExecutor

from engine.query.errors import SQLError, SQLLexError, SQLParseError
from engine.query.lexer import Lexer, Token, tokenize
from engine.query.parser import Parser, parse, parse_script
from engine.query.catalog import Catalog
from engine.query.logical_plan import LogicalPlan, LogicalPlanner
from engine.query.sql_executor import SQLExecutor
from engine.query.errors import SQLSemanticError, SQLExecutionError

__all__ = [
    "Aggregate", "BufferConfig", "ExecutionStats", "OrderKey",
    "external_hash_group_by", "external_hash_join", "external_sort",
    "Plan", "QueryPlanner", "QueryExecutor",
    "Lexer", "Token", "tokenize", "Parser", "parse", "parse_script",
    "SQLError", "SQLLexError", "SQLParseError",
    "Catalog", "LogicalPlan", "LogicalPlanner", "SQLExecutor",
    "SQLSemanticError", "SQLExecutionError",
    "IndexInfo", "TableStats",
]